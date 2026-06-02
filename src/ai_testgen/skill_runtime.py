from __future__ import annotations

import json
import re
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Mapping, Protocol

import ai_testgen.schemas as schema_contracts
from ai_testgen.artifact_store import ArtifactStore, ArtifactStoreError, StoredArtifact
from ai_testgen.schemas import (
    SchemaModel,
    SchemaValidationError,
    SkillDefinition,
    SkillRunRecord,
    SkillRunStatus,
)


SKILL_RUNS_STAGE = "skill_runs"


class SkillRuntimeError(Exception):
    """Base error for Skill Runtime failures."""


class SkillDefinitionNotFoundError(SkillRuntimeError):
    """Raised when a skill definition file is missing."""


class MalformedSkillDefinitionError(SkillRuntimeError):
    """Raised when a skill definition file is not valid JSON."""


class InvalidSkillDefinitionError(SkillRuntimeError):
    """Raised when a skill definition violates C06 validation rules."""


class SkillExecutionError(SkillRuntimeError):
    """Raised when skill execution or I/O validation fails."""


class SkillExecutionAdapter(Protocol):
    def execute(
        self,
        skill_definition: SkillDefinition,
        input_artifacts: list[SchemaModel],
    ) -> Mapping[str, Any] | SchemaModel | list[Mapping[str, Any] | SchemaModel]:
        """Execute a runtime skill and return output artifact data."""

    def skill_run_metadata(self) -> Mapping[str, Any] | None:
        """Return safe adapter metadata to attach to SkillRunRecord artifacts."""


@dataclass(frozen=True)
class ArtifactPathContext:
    path: Path
    project_id: str
    run_id: str
    stage: str
    artifact_name: str
    version: int


class SkillRuntime:
    def __init__(
        self,
        *,
        artifact_root: str | Path = "artifacts",
        adapter: SkillExecutionAdapter | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.adapter = adapter

    def run_skill(
        self,
        skill_definition: SkillDefinition,
        *,
        input_artifact_paths: list[str | Path],
        output_artifact_paths: list[str | Path],
        skill_run_id: str,
    ) -> SkillRunRecord:
        input_contexts = self._artifact_contexts(input_artifact_paths, "input_artifact_paths")
        output_contexts = self._artifact_contexts(output_artifact_paths, "output_artifact_paths")
        run_context = _shared_run_context(input_contexts + output_contexts)
        input_paths = [self._recorded_path(context.path) for context in input_contexts]
        output_paths = [self._recorded_path(context.path) for context in output_contexts]
        self._ensure_run_record_available(run_context, skill_run_id)
        skill_id = _record_skill_id(skill_definition)

        try:
            definition = validate_skill_definition(skill_definition)
            skill_id = definition.skill_id
            input_contract = _contract_type(definition.input_contract)
            output_contract = _contract_type(definition.output_contract)
            inputs = [
                self._load_model(input_contract, context)
                for context in input_contexts
            ]
            if self.adapter is None:
                raise SkillExecutionError("SkillRuntime requires an execution adapter")

            raw_outputs = self.adapter.execute(definition, inputs)
            outputs = [
                _validate_contract_data(output_contract, raw_output)
                for raw_output in _normalize_outputs(raw_outputs, len(output_contexts))
            ]
            for context, output in zip(output_contexts, outputs):
                self._write_model(context, output)

            record_data: dict[str, Any] = {
                "skill_run_id": skill_run_id,
                "skill_id": skill_id,
                "status": SkillRunStatus.SUCCEEDED.value,
                "input_artifact_paths": input_paths,
                "output_artifact_paths": output_paths,
            }
            metadata = _adapter_metadata(self.adapter)
            if metadata is not None:
                record_data["metadata"] = metadata
            record = SkillRunRecord.from_dict(record_data)
            self._write_run_record(run_context, record)
            return record
        except Exception as exc:
            if isinstance(exc, SkillExecutionError):
                error = str(exc)
            else:
                error = str(exc) or exc.__class__.__name__
            record_data = {
                "skill_run_id": skill_run_id,
                "skill_id": skill_id,
                "status": SkillRunStatus.FAILED.value,
                "input_artifact_paths": input_paths,
                "output_artifact_paths": output_paths,
                "error": error,
            }
            metadata = _adapter_metadata(self.adapter)
            if metadata is not None:
                record_data["metadata"] = metadata
            record = SkillRunRecord.from_dict(record_data)
            self._write_run_record(run_context, record)
            raise SkillExecutionError(error) from exc

    def _artifact_contexts(
        self,
        artifact_paths: list[str | Path],
        field_name: str,
    ) -> list[ArtifactPathContext]:
        if not artifact_paths:
            raise SkillExecutionError(f"{field_name} must be a non-empty list")
        return [self._artifact_context(path) for path in artifact_paths]

    def _artifact_context(self, artifact_path: str | Path) -> ArtifactPathContext:
        path = Path(artifact_path)
        root = self.artifact_root.resolve(strict=False)
        target = path.resolve(strict=False)
        try:
            relative = target.relative_to(root)
        except ValueError as exc:
            raise SkillExecutionError(f"Artifact path must be under artifact_root: {path}") from exc

        parts = relative.parts
        if len(parts) < 4:
            raise SkillExecutionError(f"Artifact path must include project, run, stage, and file: {path}")
        project_id = parts[0]
        run_id = parts[1]
        stage = "/".join(parts[2:-1])
        artifact_name, version = _artifact_name_and_version(parts[-1])
        return ArtifactPathContext(
            path=target,
            project_id=project_id,
            run_id=run_id,
            stage=stage,
            artifact_name=artifact_name,
            version=version,
        )

    def _load_model(
        self,
        model_type: type[SchemaModel],
        context: ArtifactPathContext,
    ) -> SchemaModel:
        store = ArtifactStore(self.artifact_root)
        try:
            return store.load_model(
                model_type,
                context.project_id,
                context.run_id,
                context.stage,
                context.artifact_name,
                version=context.version,
            )
        except (ArtifactStoreError, SchemaValidationError) as exc:
            raise SkillExecutionError(str(exc)) from exc

    def _write_model(self, context: ArtifactPathContext, model: SchemaModel) -> StoredArtifact:
        store = ArtifactStore(self.artifact_root)
        try:
            return store.write_json(
                context.project_id,
                context.run_id,
                context.stage,
                context.artifact_name,
                model,
                version=context.version,
            )
        except ArtifactStoreError as exc:
            raise SkillExecutionError(str(exc)) from exc

    def _write_run_record(
        self,
        run_context: tuple[str, str],
        record: SkillRunRecord,
    ) -> StoredArtifact:
        project_id, run_id = run_context
        store = ArtifactStore(self.artifact_root)
        try:
            return store.write_json(
                project_id,
                run_id,
                SKILL_RUNS_STAGE,
                record.skill_run_id,
                record,
                version=1,
            )
        except ArtifactStoreError as exc:
            raise SkillExecutionError(str(exc)) from exc

    def _ensure_run_record_available(
        self,
        run_context: tuple[str, str],
        skill_run_id: str,
    ) -> None:
        project_id, run_id = run_context
        store = ArtifactStore(self.artifact_root)
        try:
            if store.exists(project_id, run_id, SKILL_RUNS_STAGE, skill_run_id, version=1):
                raise SkillExecutionError(f"SkillRunRecord already exists: {skill_run_id}")
        except ArtifactStoreError as exc:
            raise SkillExecutionError(str(exc)) from exc

    def _recorded_path(self, path: Path) -> str:
        relative = path.resolve(strict=False).relative_to(self.artifact_root.resolve(strict=False))
        return Path("artifacts", *relative.parts).as_posix()


def load_skill_definition(path: str | Path) -> SkillDefinition:
    definition_path = Path(path)
    if not definition_path.exists():
        raise SkillDefinitionNotFoundError(f"SkillDefinition file not found: {definition_path}")

    try:
        data = json.loads(definition_path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise MalformedSkillDefinitionError(f"Malformed SkillDefinition JSON: {definition_path}") from exc

    if not isinstance(data, Mapping):
        raise InvalidSkillDefinitionError("SkillDefinition JSON must be a mapping")

    try:
        definition = SkillDefinition.from_dict(data)
    except SchemaValidationError as exc:
        raise InvalidSkillDefinitionError(f"Invalid SkillDefinition: {exc}") from exc
    return validate_skill_definition(definition)


def validate_skill_definition(definition: SkillDefinition) -> SkillDefinition:
    try:
        validated = SkillDefinition.from_dict(definition.to_dict())
    except SchemaValidationError as exc:
        raise InvalidSkillDefinitionError(f"Invalid SkillDefinition: {exc}") from exc

    _contract_type(validated.input_contract)
    _contract_type(validated.output_contract)
    return validated


def _contract_type(contract_name: str) -> type[SchemaModel]:
    contract = getattr(schema_contracts, contract_name, None)
    if not isinstance(contract, type) or not issubclass(contract, SchemaModel) or contract is SchemaModel:
        raise InvalidSkillDefinitionError(f"Unknown skill contract: {contract_name}")
    return contract


def _record_skill_id(skill_definition: SkillDefinition) -> str:
    skill_id = getattr(skill_definition, "skill_id", "")
    return skill_id if isinstance(skill_id, str) and skill_id.strip() else "unknown_skill"


def _validate_contract_data(
    model_type: type[SchemaModel],
    data: Mapping[str, Any] | SchemaModel,
) -> SchemaModel:
    if isinstance(data, model_type):
        return data
    if isinstance(data, SchemaModel):
        data = data.to_dict()
    if not isinstance(data, Mapping):
        raise SkillExecutionError(f"{model_type.__name__} output must be a mapping or SchemaModel")
    try:
        return model_type.from_dict(data)
    except SchemaValidationError as exc:
        raise SkillExecutionError(str(exc)) from exc


def _normalize_outputs(
    raw_outputs: Mapping[str, Any] | SchemaModel | list[Mapping[str, Any] | SchemaModel],
    expected_count: int,
) -> list[Mapping[str, Any] | SchemaModel]:
    if expected_count == 1 and not isinstance(raw_outputs, list):
        return [raw_outputs]
    if not isinstance(raw_outputs, list):
        raise SkillExecutionError("Skill adapter must return one output per output artifact path")
    if len(raw_outputs) != expected_count:
        raise SkillExecutionError("Skill adapter output count must match output_artifact_paths")
    return raw_outputs


def _adapter_metadata(adapter: SkillExecutionAdapter | None) -> dict[str, Any] | None:
    if adapter is None:
        return None
    metadata_hook = getattr(adapter, "skill_run_metadata", None)
    if metadata_hook is None:
        return None
    if not callable(metadata_hook):
        raise SkillExecutionError("Skill adapter metadata hook must be callable")
    metadata = metadata_hook()
    if metadata is None:
        return None
    if not isinstance(metadata, Mapping):
        raise SkillExecutionError("Skill adapter metadata must be a mapping")
    cleaned = {
        key: value
        for key, value in metadata.items()
        if value is not None
    }
    return cleaned or None


def _artifact_name_and_version(file_name: str) -> tuple[str, int]:
    match = re.fullmatch(r"(.+?)(?:\.v([1-9]\d*))?\.json", file_name)
    if match is None:
        raise SkillExecutionError(f"Artifact file must be a .json file: {file_name}")
    artifact_name = match.group(1)
    version = int(match.group(2) or "1")
    return artifact_name, version


def _shared_run_context(contexts: list[ArtifactPathContext]) -> tuple[str, str]:
    if not contexts:
        raise SkillExecutionError("At least one artifact path is required")
    project_id = contexts[0].project_id
    run_id = contexts[0].run_id
    for context in contexts[1:]:
        if context.project_id != project_id or context.run_id != run_id:
            raise SkillExecutionError("All skill artifacts must share the same project_id and run_id")
    return project_id, run_id
