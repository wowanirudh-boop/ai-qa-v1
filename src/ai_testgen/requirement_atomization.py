from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import count
from pathlib import Path

from ai_testgen.artifact_store import ArtifactStore, ArtifactStoreError
from ai_testgen.schemas import (
    AtomicRequirement,
    AtomicRequirementLedger,
    AtomicRequirementStatus,
    CandidateRequirement,
    CandidateRequirementPackage,
    RequirementOrigin,
    SchemaValidationError,
    SkillDefinition,
    SkillRunRecord,
    SourceRef,
)
from ai_testgen.skill_runtime import (
    InvalidSkillDefinitionError,
    SkillRuntime,
    SkillRuntimeError,
    load_skill_definition,
    validate_skill_definition,
)
from ai_testgen.skill_runtime_config import create_skill_runtime_for_run


CANDIDATE_REQUIREMENTS_STAGE = "03_candidate_requirements"
CANDIDATE_REQUIREMENT_PACKAGE_ARTIFACT_NAME = "candidate_requirement_package"
ATOMIC_REQUIREMENTS_STAGE = "04_atomic_requirements"
ATOMIC_REQUIREMENT_LEDGER_ARTIFACT_NAME = "atomic_requirement_ledger"
RAW_ATOMIC_REQUIREMENT_LEDGER_ARTIFACT_NAME = "atomic_requirement_ledger_skill_output"
DEFAULT_SKILL_DEFINITION_PATH = Path("skills") / "requirement_atomization_v1.json"
REQUIREMENT_ATOMIZATION_INPUT_CONTRACT = "CandidateRequirementPackage"
REQUIREMENT_ATOMIZATION_OUTPUT_CONTRACT = "AtomicRequirementLedger"
ATOMIC_LEDGER_ID = "atomic_ledger_001"
SAFE_AND_SPLIT_VERBS = {
    "accept",
    "allow",
    "ask",
    "block",
    "capture",
    "collect",
    "confirm",
    "create",
    "delete",
    "display",
    "escalate",
    "explain",
    "list",
    "mask",
    "prevent",
    "provide",
    "redact",
    "reject",
    "return",
    "route",
    "search",
    "send",
    "show",
    "summarize",
    "support",
    "update",
    "validate",
    "verify",
}
TRAILING_FRAGMENT_WORDS = {
    "about",
    "after",
    "as",
    "at",
    "before",
    "between",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "through",
    "to",
    "under",
    "with",
    "without",
}


class RequirementAtomizationError(Exception):
    """Base error for C08 requirement atomization failures."""


class CandidatePackageArtifactError(RequirementAtomizationError):
    """Raised when the input CandidateRequirementPackage artifact cannot be used."""


class InvalidRequirementAtomizationSkillError(RequirementAtomizationError):
    """Raised when the atomization SkillDefinition does not match C08 contracts."""


class RequirementAtomizationSkillError(RequirementAtomizationError):
    """Raised when the Skill Runtime fails the atomization run."""


class InvalidAtomicRequirementLedgerError(RequirementAtomizationError):
    """Raised when atomized requirements fail C08 validation."""


class RequirementAtomizationPersistenceError(RequirementAtomizationError):
    """Raised when C08 cannot persist its output artifact."""


@dataclass(frozen=True)
class RequirementAtomizationResult:
    atomic_ledger: AtomicRequirementLedger
    atomic_ledger_path: Path
    skill_run_record: SkillRunRecord
    skill_run_record_path: Path


def atomize_requirements_from_candidate_package_artifact(
    candidate_package_path: str | Path,
    skill_definition: SkillDefinition | str | Path | None = None,
    *,
    skill_runtime: SkillRuntime | None = None,
    skill_adapter: str | None = None,
    skill_run_id: str | None = None,
) -> RequirementAtomizationResult:
    candidate_path = Path(candidate_package_path)
    artifact_root, project_id, run_id = _artifact_context_from_candidate_package_path(candidate_path)
    store = ArtifactStore(artifact_root)
    candidate_package = _load_candidate_package(store, project_id=project_id, run_id=run_id)
    if candidate_package.project_id != project_id:
        raise CandidatePackageArtifactError(
            f"CandidateRequirementPackage artifact project directory must match project_id "
            f"{candidate_package.project_id}: {candidate_path}"
        )

    atomic_ledger, skill_run_record = _atomize_with_skill(
        store,
        candidate_path=candidate_path,
        candidate_package=candidate_package,
        project_id=project_id,
        run_id=run_id,
        skill_definition=DEFAULT_SKILL_DEFINITION_PATH if skill_definition is None else skill_definition,
        skill_runtime=skill_runtime,
        skill_adapter=skill_adapter,
        skill_run_id=skill_run_id,
    )
    written = _write_atomic_ledger(store, run_id=run_id, atomic_ledger=atomic_ledger)

    return RequirementAtomizationResult(
        atomic_ledger=atomic_ledger,
        atomic_ledger_path=written.path,
        skill_run_record=skill_run_record,
        skill_run_record_path=store.artifact_path(project_id, run_id, "skill_runs", skill_run_record.skill_run_id),
    )


def atomize_candidate_package_deterministic_for_tests(
    candidate_package: CandidateRequirementPackage,
) -> AtomicRequirementLedger:
    requirements: list[AtomicRequirement] = []
    next_id = count(1)
    for candidate in candidate_package.candidates:
        for statement in _atomic_statements(candidate.statement):
            requirements.append(_atomic_requirement_from_candidate(candidate, statement, next(next_id)))

    try:
        ledger = AtomicRequirementLedger.from_dict(
            {
                "atomic_ledger_id": ATOMIC_LEDGER_ID,
                "project_id": candidate_package.project_id,
                "candidate_package_id": candidate_package.candidate_package_id,
                "requirements": [requirement.to_dict() for requirement in requirements],
            }
        )
    except SchemaValidationError as exc:
        raise InvalidAtomicRequirementLedgerError(f"Invalid AtomicRequirementLedger data: {exc}") from exc

    validate_atomic_ledger_against_candidates(ledger, candidate_package)
    return ledger


def validate_atomic_ledger_against_candidates(
    atomic_ledger: AtomicRequirementLedger,
    candidate_package: CandidateRequirementPackage,
) -> None:
    if atomic_ledger.project_id != candidate_package.project_id:
        raise InvalidAtomicRequirementLedgerError("AtomicRequirementLedger project_id must match CandidateRequirementPackage")
    if atomic_ledger.candidate_package_id != candidate_package.candidate_package_id:
        raise InvalidAtomicRequirementLedgerError(
            "AtomicRequirementLedger candidate_package_id must match CandidateRequirementPackage"
        )

    candidates_by_id = {
        candidate.candidate_id: candidate
        for candidate in candidate_package.candidates
    }
    for requirement in atomic_ledger.requirements:
        if requirement.candidate_ids is not None:
            for candidate_id in requirement.candidate_ids:
                if candidate_id not in candidates_by_id:
                    raise InvalidAtomicRequirementLedgerError(
                        f"requirement {requirement.requirement_id} references unknown candidate {candidate_id}"
                    )
        if requirement.origin == RequirementOrigin.SOURCE_DERIVED:
            _validate_source_derived_requirement_traceability(requirement, candidates_by_id)


def _atomize_with_skill(
    store: ArtifactStore,
    *,
    candidate_path: Path,
    candidate_package: CandidateRequirementPackage,
    project_id: str,
    run_id: str,
    skill_definition: SkillDefinition | str | Path,
    skill_runtime: SkillRuntime | None,
    skill_adapter: str | None,
    skill_run_id: str | None,
) -> tuple[AtomicRequirementLedger, SkillRunRecord]:
    definition = _load_requirement_atomization_skill_definition(skill_definition)
    raw_atomic_path, raw_atomic_version = _next_artifact_path(
        store,
        project_id,
        run_id,
        ATOMIC_REQUIREMENTS_STAGE,
        RAW_ATOMIC_REQUIREMENT_LEDGER_ARTIFACT_NAME,
    )
    run_id_for_skill = skill_run_id or _next_skill_run_id(store, project_id, run_id)

    try:
        runtime = skill_runtime or create_skill_runtime_for_run(
            artifact_root=store.artifact_root,
            project_id=project_id,
            run_id=run_id,
            adapter_name=skill_adapter,
        )
        skill_run_record = runtime.run_skill(
            definition,
            input_artifact_paths=[candidate_path],
            output_artifact_paths=[raw_atomic_path],
            skill_run_id=run_id_for_skill,
        )
    except SkillRuntimeError as exc:
        raise RequirementAtomizationSkillError(f"Requirement atomization skill failed: {exc}") from exc

    raw_atomic_ledger = _load_atomic_ledger(
        store,
        project_id=project_id,
        run_id=run_id,
        artifact_name=RAW_ATOMIC_REQUIREMENT_LEDGER_ARTIFACT_NAME,
        version=raw_atomic_version,
    )
    validate_atomic_ledger_against_candidates(raw_atomic_ledger, candidate_package)
    return _atomic_ledger_with_deterministic_ids(raw_atomic_ledger), skill_run_record


def _atomic_requirement_from_candidate(
    candidate: CandidateRequirement,
    statement: str,
    sequence: int,
) -> AtomicRequirement:
    try:
        return AtomicRequirement.from_dict(
            {
                "requirement_id": f"req_{sequence:03d}",
                "statement": statement,
                "requirement_type": candidate.requirement_type_guess,
                "status": AtomicRequirementStatus.ATOMIC_DRAFT.value,
                "origin": RequirementOrigin.SOURCE_DERIVED.value,
                "source_refs": [source_ref.to_dict() for source_ref in candidate.source_refs],
                "candidate_ids": [candidate.candidate_id],
            }
        )
    except SchemaValidationError as exc:
        raise InvalidAtomicRequirementLedgerError(f"Invalid AtomicRequirement data: {exc}") from exc


def _atomic_statements(statement: str) -> list[str]:
    normalized = " ".join(statement.split())
    sentence_parts = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", normalized)
        if part.strip()
    ]
    if len(sentence_parts) > 1:
        return [_sentence_with_terminal_punctuation(part) for part in sentence_parts]

    semicolon_parts = [part.strip() for part in normalized.rstrip(".!?").split(";") if part.strip()]
    if len(semicolon_parts) > 1:
        return [_sentence_with_terminal_punctuation(part) for part in semicolon_parts]

    return _split_simple_must_and_statement(normalized)


def _split_simple_must_and_statement(statement: str) -> list[str]:
    stripped = statement.strip().rstrip(".!?")
    match = re.fullmatch(r"(?P<prefix>The bot must )(?P<body>.+)", stripped, flags=re.IGNORECASE)
    if match is None:
        return [_sentence_with_terminal_punctuation(statement)]

    prefix = match.group("prefix")
    body = match.group("body")
    parts = [part.strip() for part in re.split(r"\s+and\s+", body) if part.strip()]
    if len(parts) <= 1:
        return [_sentence_with_terminal_punctuation(statement)]
    if any(_ends_with_fragment_word(part) for part in parts):
        return [_sentence_with_terminal_punctuation(statement)]
    if not all(_starts_with_safe_split_verb(part) for part in parts[1:]):
        return [_sentence_with_terminal_punctuation(statement)]

    prefix_lower = prefix.lower()
    statements = [
        part if part.lower().startswith(prefix_lower) else f"{prefix}{part}"
        for part in parts
    ]
    return [_sentence_with_terminal_punctuation(part) for part in statements]


def _starts_with_safe_split_verb(statement_part: str) -> bool:
    first_word = statement_part.split(maxsplit=1)[0].strip(" ,:;").lower()
    return first_word in SAFE_AND_SPLIT_VERBS


def _ends_with_fragment_word(statement_part: str) -> bool:
    words = statement_part.split()
    if not words:
        return True
    return words[-1].strip(" ,:;").lower() in TRAILING_FRAGMENT_WORDS


def _sentence_with_terminal_punctuation(statement: str) -> str:
    stripped = statement.strip()
    if stripped.endswith((".", "!", "?")):
        return stripped
    return f"{stripped}."


def _validate_source_derived_requirement_traceability(
    requirement: AtomicRequirement,
    candidates_by_id: dict[str, CandidateRequirement],
) -> None:
    if not requirement.candidate_ids:
        raise InvalidAtomicRequirementLedgerError(
            f"source-derived requirement {requirement.requirement_id} must preserve candidate_ids"
        )

    expected_refs: list[SourceRef] = []
    for candidate_id in requirement.candidate_ids:
        expected_refs.extend(candidates_by_id[candidate_id].source_refs)

    if _normalized_source_refs(requirement.source_refs) != _normalized_source_refs(expected_refs):
        raise InvalidAtomicRequirementLedgerError(
            f"source-derived requirement {requirement.requirement_id} source_refs must match linked candidates"
        )


def _normalized_source_refs(source_refs: Iterable[SourceRef] | None) -> list[tuple[tuple[str, str], ...]]:
    return sorted(
        tuple(sorted(source_ref.to_dict().items()))
        for source_ref in (source_refs or [])
    )


def _load_requirement_atomization_skill_definition(
    skill_definition: SkillDefinition | str | Path,
) -> SkillDefinition:
    try:
        definition = (
            skill_definition
            if isinstance(skill_definition, SkillDefinition)
            else load_skill_definition(skill_definition)
        )
        validated = validate_skill_definition(definition)
    except (InvalidSkillDefinitionError, SchemaValidationError, SkillRuntimeError) as exc:
        raise InvalidRequirementAtomizationSkillError(f"Invalid requirement atomization SkillDefinition: {exc}") from exc

    if validated.input_contract != REQUIREMENT_ATOMIZATION_INPUT_CONTRACT:
        raise InvalidRequirementAtomizationSkillError(
            f"Requirement atomization skill input_contract must be {REQUIREMENT_ATOMIZATION_INPUT_CONTRACT}"
        )
    if validated.output_contract != REQUIREMENT_ATOMIZATION_OUTPUT_CONTRACT:
        raise InvalidRequirementAtomizationSkillError(
            f"Requirement atomization skill output_contract must be {REQUIREMENT_ATOMIZATION_OUTPUT_CONTRACT}"
        )
    return validated


def _load_candidate_package(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
) -> CandidateRequirementPackage:
    try:
        return store.load_model(
            CandidateRequirementPackage,
            project_id,
            run_id,
            CANDIDATE_REQUIREMENTS_STAGE,
            CANDIDATE_REQUIREMENT_PACKAGE_ARTIFACT_NAME,
        )
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise CandidatePackageArtifactError(f"Failed to load CandidateRequirementPackage artifact: {exc}") from exc


def _load_atomic_ledger(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
    artifact_name: str,
    version: int,
) -> AtomicRequirementLedger:
    try:
        return store.load_model(
            AtomicRequirementLedger,
            project_id,
            run_id,
            ATOMIC_REQUIREMENTS_STAGE,
            artifact_name,
            version=version,
        )
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise InvalidAtomicRequirementLedgerError(
            f"Failed to load AtomicRequirementLedger artifact: {exc}"
        ) from exc


def _write_atomic_ledger(
    store: ArtifactStore,
    *,
    run_id: str,
    atomic_ledger: AtomicRequirementLedger,
):
    try:
        return store.write_json(
            atomic_ledger.project_id,
            run_id,
            ATOMIC_REQUIREMENTS_STAGE,
            ATOMIC_REQUIREMENT_LEDGER_ARTIFACT_NAME,
            atomic_ledger,
        )
    except ArtifactStoreError as exc:
        raise RequirementAtomizationPersistenceError(
            f"Failed to save AtomicRequirementLedger artifact: {exc}"
        ) from exc


def _atomic_ledger_with_deterministic_ids(
    atomic_ledger: AtomicRequirementLedger,
) -> AtomicRequirementLedger:
    data = atomic_ledger.to_dict()
    data["atomic_ledger_id"] = ATOMIC_LEDGER_ID
    for index, requirement in enumerate(data["requirements"], start=1):
        requirement["requirement_id"] = f"req_{index:03d}"
    try:
        return AtomicRequirementLedger.from_dict(data)
    except SchemaValidationError as exc:
        raise InvalidAtomicRequirementLedgerError(
            f"Invalid deterministic AtomicRequirementLedger data: {exc}"
        ) from exc


def _artifact_context_from_candidate_package_path(path: Path) -> tuple[Path, str, str]:
    if path.name != "candidate_requirement_package.json":
        raise CandidatePackageArtifactError(
            f"CandidateRequirementPackage artifact must be named candidate_requirement_package.json: {path}"
        )
    if path.parent.name != CANDIDATE_REQUIREMENTS_STAGE:
        raise CandidatePackageArtifactError(
            f"CandidateRequirementPackage artifact must be under {CANDIDATE_REQUIREMENTS_STAGE}: {path}"
        )
    run_dir = path.parent.parent
    project_dir = run_dir.parent
    return project_dir.parent, project_dir.name, run_dir.name


def _next_artifact_path(
    store: ArtifactStore,
    project_id: str,
    run_id: str,
    stage: str,
    artifact_name: str,
) -> tuple[Path, int]:
    for version in count(1):
        if not store.exists(project_id, run_id, stage, artifact_name, version=version):
            return store.artifact_path(project_id, run_id, stage, artifact_name, version=version), version
    raise AssertionError("unreachable")


def _next_skill_run_id(store: ArtifactStore, project_id: str, run_id: str) -> str:
    for index in count(1):
        skill_run_id = f"skill_run_{index:03d}"
        if not store.exists(project_id, run_id, "skill_runs", skill_run_id):
            return skill_run_id
    raise AssertionError("unreachable")
