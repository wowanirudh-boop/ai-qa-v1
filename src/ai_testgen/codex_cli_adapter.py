from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ai_testgen.schemas import SchemaModel, SkillDefinition
from ai_testgen.skill_runtime import SkillExecutionError


CODEX_CLI_ADAPTER_NAME = "codex_cli"
CODEX_CLI_COMMAND_ENV = "AI_TESTGEN_CODEX_CLI_COMMAND"
DEFAULT_CODEX_CLI_COMMAND = "codex"
DEFAULT_CODEX_CLI_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class CodexCliCompletedProcess:
    returncode: int
    stdout: str
    stderr: str


CodexCliRunner = Callable[[Sequence[str], str, int, Path | None], CodexCliCompletedProcess]


class CodexCliSkillAdapter:
    """C06 adapter that executes runtime skills through the local Codex CLI."""

    def __init__(
        self,
        *,
        command: str | Path | None = None,
        runner: CodexCliRunner | None = None,
        cwd: str | Path | None = None,
    ) -> None:
        self.command = str(command or os.environ.get(CODEX_CLI_COMMAND_ENV) or DEFAULT_CODEX_CLI_COMMAND)
        self.runner = runner or _run_codex_cli
        self.cwd = Path(cwd) if cwd is not None else None

    def execute(
        self,
        skill_definition: SkillDefinition,
        input_artifacts: list[SchemaModel],
    ) -> Mapping[str, Any] | SchemaModel | list[Mapping[str, Any] | SchemaModel]:
        prompt = _build_prompt(skill_definition, input_artifacts)
        timeout_seconds = skill_definition.timeout_seconds or DEFAULT_CODEX_CLI_TIMEOUT_SECONDS
        with tempfile.TemporaryDirectory(prefix="ai-testgen-codex-") as temp_dir:
            temp_path = Path(temp_dir)
            output_path = temp_path / "last_message.json"
            schema_path = temp_path / "output_schema.json"
            args = [
                self.command,
                "exec",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--ephemeral",
                "--output-last-message",
                str(output_path),
                "-",
            ]
            output_schema = _output_schema_for_contract(skill_definition.output_contract)
            if output_schema is not None:
                schema_path.write_text(
                    json.dumps(output_schema, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                args[5:5] = ["--output-schema", str(schema_path)]
            result = self._run(args, prompt, timeout_seconds)
            if result.returncode != 0:
                details = (result.stderr or result.stdout).strip()
                raise SkillExecutionError(f"Codex CLI failed with exit code {result.returncode}: {details}")
            output_text = output_path.read_text(encoding="utf-8") if output_path.exists() else result.stdout
        return _parse_json_output(output_text)

    def _run(self, args: Sequence[str], prompt: str, timeout_seconds: int) -> CodexCliCompletedProcess:
        try:
            return self.runner(args, prompt, timeout_seconds, self.cwd)
        except FileNotFoundError as exc:
            raise SkillExecutionError(f"Codex CLI executable not found: {self.command}") from exc
        except PermissionError as exc:
            raise SkillExecutionError(f"Codex CLI executable is not accessible: {self.command}") from exc
        except subprocess.TimeoutExpired as exc:
            raise SkillExecutionError(f"Codex CLI timed out after {timeout_seconds} seconds") from exc
        except OSError as exc:
            raise SkillExecutionError(f"Codex CLI execution failed: {exc}") from exc


def _run_codex_cli(
    args: Sequence[str],
    prompt: str,
    timeout_seconds: int,
    cwd: Path | None,
) -> CodexCliCompletedProcess:
    completed = subprocess.run(
        list(args),
        input=prompt,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout_seconds,
        cwd=cwd,
    )
    return CodexCliCompletedProcess(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _build_prompt(skill_definition: SkillDefinition, input_artifacts: list[SchemaModel]) -> str:
    payload = {
        "skill_definition": skill_definition.to_dict(),
        "input_artifacts": [
            {
                "contract": artifact.__class__.__name__,
                "payload": artifact.to_dict(),
            }
            for artifact in input_artifacts
        ],
    }
    prompt_text = ""
    if skill_definition.metadata and isinstance(skill_definition.metadata.get("prompt_text"), str):
        prompt_text = skill_definition.metadata["prompt_text"]

    return (
        "You are executing a runtime skill for the AI Test Generation System.\n"
        "Return only one JSON object. Do not wrap it in Markdown. Do not include commentary.\n"
        f"The output JSON must conform to the {skill_definition.output_contract} data contract.\n"
        "Use only the provided input artifacts. Preserve IDs and source_refs exactly when the skill rules require it.\n"
        "Do not control workflow, write files, mutate artifacts, or produce downstream artifact types.\n"
        "Omit optional metadata fields unless the output schema explicitly includes them.\n\n"
        f"Skill prompt:\n{prompt_text}\n\n"
        "Runtime skill packet JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}\n"
    )


def _output_schema_for_contract(contract_name: str) -> dict[str, Any] | None:
    schemas = {
        "CandidateRequirementPackage": _candidate_requirement_package_schema,
        "AtomicRequirementLedger": _atomic_requirement_ledger_schema,
        "DraftTestSuite": _draft_test_suite_schema,
    }
    schema_factory = schemas.get(contract_name)
    return schema_factory() if schema_factory is not None else None


def _strict_object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _source_ref_schema() -> dict[str, Any]:
    return _strict_object(
        {
            "document_id": {"type": "string"},
            "chunk_id": {"type": "string"},
        },
        ["document_id", "chunk_id"],
    )


def _candidate_requirement_package_schema() -> dict[str, Any]:
    candidate_schema = _strict_object(
        {
            "candidate_id": {"type": "string"},
            "statement": {"type": "string"},
            "requirement_type_guess": {"type": "string"},
            "source_refs": {"type": "array", "items": _source_ref_schema()},
            "confidence": {"type": "number"},
        },
        ["candidate_id", "statement", "requirement_type_guess", "source_refs", "confidence"],
    )
    chunk_result_schema = _strict_object(
        {
            "chunk_id": {"type": "string"},
            "processing_status": {
                "type": "string",
                "enum": [
                    "requirements_extracted",
                    "non_testable_context",
                    "duplicate",
                    "out_of_scope",
                    "unclear",
                    "failed_processing",
                ],
            },
            "candidate_ids": _string_array(),
        },
        ["chunk_id", "processing_status", "candidate_ids"],
    )
    return _strict_object(
        {
            "candidate_package_id": {"type": "string"},
            "project_id": {"type": "string"},
            "source_package_id": {"type": "string"},
            "candidates": {"type": "array", "items": candidate_schema},
            "chunk_extraction_results": {"type": "array", "items": chunk_result_schema},
        },
        ["candidate_package_id", "project_id", "source_package_id", "candidates", "chunk_extraction_results"],
    )


def _atomic_requirement_ledger_schema() -> dict[str, Any]:
    requirement_schema = _strict_object(
        {
            "requirement_id": {"type": "string"},
            "statement": {"type": "string"},
            "requirement_type": {"type": "string"},
            "status": {"type": "string"},
            "origin": {"type": "string"},
            "source_refs": {"type": "array", "items": _source_ref_schema()},
            "candidate_ids": _string_array(),
        },
        ["requirement_id", "statement", "requirement_type", "status", "origin", "source_refs", "candidate_ids"],
    )
    return _strict_object(
        {
            "atomic_ledger_id": {"type": "string"},
            "project_id": {"type": "string"},
            "candidate_package_id": {"type": "string"},
            "requirements": {"type": "array", "items": requirement_schema},
        },
        ["atomic_ledger_id", "project_id", "candidate_package_id", "requirements"],
    )


def _draft_test_suite_schema() -> dict[str, Any]:
    turn_schema = _strict_object(
        {
            "turn_id": {"type": "string"},
            "speaker": {"type": "string", "enum": ["user", "bot", "system"]},
            "text": {"type": "string"},
        },
        ["turn_id", "speaker", "text"],
    )
    assertion_schema = _strict_object(
        {
            "assertion_id": {"type": "string"},
            "assertion_type": {"type": "string"},
            "target": {"type": "string"},
            "expected": {"type": "string"},
        },
        ["assertion_id", "assertion_type", "target", "expected"],
    )
    test_case_schema = _strict_object(
        {
            "test_case_id": {"type": "string"},
            "title": {"type": "string"},
            "status": {"type": "string", "enum": ["draft"]},
            "requirement_ids": _string_array(),
            "obligation_ids": _string_array(),
            "source_refs": {"type": "array", "items": _source_ref_schema()},
            "turns": {"type": "array", "items": turn_schema},
            "assertions": {"type": "array", "items": assertion_schema},
        },
        [
            "test_case_id",
            "title",
            "status",
            "requirement_ids",
            "obligation_ids",
            "source_refs",
            "turns",
            "assertions",
        ],
    )
    return _strict_object(
        {
            "draft_suite_id": {"type": "string"},
            "project_id": {"type": "string"},
            "obligation_ledger_id": {"type": "string"},
            "test_cases": {"type": "array", "items": test_case_schema},
        },
        ["draft_suite_id", "project_id", "obligation_ledger_id", "test_cases"],
    )


def _parse_json_output(output_text: str) -> Mapping[str, Any]:
    try:
        output = json.loads(output_text)
    except JSONDecodeError as exc:
        raise SkillExecutionError("Codex CLI output was not valid JSON") from exc
    if not isinstance(output, Mapping):
        raise SkillExecutionError("Codex CLI output JSON must be an object")
    return output
