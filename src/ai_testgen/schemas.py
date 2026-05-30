from __future__ import annotations

from dataclasses import MISSING, dataclass, fields
from enum import StrEnum
from math import isfinite
from types import UnionType
from typing import Any, ClassVar, Mapping, Union, get_args, get_origin, get_type_hints


class SchemaValidationError(ValueError):
    """Raised when a data contract fails deterministic schema validation."""


class DocumentIngestionStatus(StrEnum):
    LOADED = "loaded"
    SKIPPED = "skipped"
    FAILED = "failed"


class SourceChunkProcessingStatus(StrEnum):
    NOT_PROCESSED = "not_processed"
    REQUIREMENTS_EXTRACTED = "requirements_extracted"
    NON_TESTABLE_CONTEXT = "non_testable_context"
    DUPLICATE = "duplicate"
    OUT_OF_SCOPE = "out_of_scope"
    UNCLEAR = "unclear"
    FAILED_PROCESSING = "failed_processing"


class AtomicRequirementStatus(StrEnum):
    CANDIDATE = "candidate"
    ATOMIC_DRAFT = "atomic_draft"
    VALIDATED = "validated"
    DUPLICATE = "duplicate"
    CONFLICTING = "conflicting"
    NEEDS_CLARIFICATION = "needs_clarification"
    INFERRED = "inferred"
    OUT_OF_SCOPE = "out_of_scope"
    REJECTED = "rejected"


class RequirementOrigin(StrEnum):
    SOURCE_DERIVED = "source_derived"
    INFERRED = "inferred"
    ASSUMPTION = "assumption"
    USER_ADDED = "user_added"
    SYSTEM_DEFAULT = "system_default"


class TestObligationStatus(StrEnum):
    PLANNED = "planned"
    GENERATED = "generated"
    COVERED = "covered"
    BLOCKED_MISSING_DATA = "blocked_missing_data"
    BLOCKED_UNCLEAR_REQUIREMENT = "blocked_unclear_requirement"
    SKIPPED_BY_POLICY = "skipped_by_policy"
    REJECTED = "rejected"


class ConversationSpeaker(StrEnum):
    USER = "user"
    BOT = "bot"
    SYSTEM = "system"


class TestCaseStatus(StrEnum):
    DRAFT = "draft"
    VALID = "valid"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPORTED = "exported"


class SkillRunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PipelineRunStatus(StrEnum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


NON_SOURCE_REQUIREMENT_ORIGINS = {
    RequirementOrigin.INFERRED,
    RequirementOrigin.ASSUMPTION,
    RequirementOrigin.USER_ADDED,
    RequirementOrigin.SYSTEM_DEFAULT,
}

EXPORTABLE_TEST_STATUSES = {
    TestCaseStatus.VALID,
    TestCaseStatus.APPROVED,
    TestCaseStatus.EXPORTED,
}

NORMAL_OBLIGATION_STATUSES = {
    TestObligationStatus.PLANNED,
    TestObligationStatus.GENERATED,
    TestObligationStatus.COVERED,
}

PIPELINE_RUN_STAGES = [
    "C03_project_config",
    "C04_document_ingestion",
    "C05_source_ledger",
    "C06_skill_runtime",
    "C07_requirement_extraction",
    "C08_requirement_atomization",
    "C09_requirement_governance",
    "C10_obligation_planning",
    "C11_test_generation",
    "C12_test_validation_coverage",
    "C13_review_report",
    "C14_executor_export",
    "C15_orchestrator",
]

KNOWN_COMPONENT_STAGES = {
    "C00_bootstrap",
    "C01_schemas",
    "C02_artifact_store",
    *PIPELINE_RUN_STAGES,
}


class SchemaModel:
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SchemaModel":
        if not isinstance(data, Mapping):
            raise SchemaValidationError(f"{cls.__name__}.from_dict expected a mapping")

        model_fields = {field.name: field for field in fields(cls)}
        unknown_fields = sorted(set(data) - set(model_fields))
        if unknown_fields:
            unknown = ", ".join(unknown_fields)
            raise SchemaValidationError(f"Unknown field(s) for {cls.__name__}: {unknown}")

        missing_fields = [
            field.name
            for field in fields(cls)
            if field.default is MISSING and field.default_factory is MISSING and field.name not in data
        ]
        if missing_fields:
            missing = ", ".join(missing_fields)
            raise SchemaValidationError(f"Missing required field(s) for {cls.__name__}: {missing}")

        hints = get_type_hints(cls)
        values = {
            name: _coerce_value(value, hints[name], f"{cls.__name__}.{name}")
            for name, value in data.items()
        }
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if value is None:
                continue
            result[field.name] = _to_jsonable(value)
        return result

    def _validate(self) -> None:
        return None

    def __post_init__(self) -> None:
        self._validate()


def _coerce_value(value: Any, annotation: Any, field_path: str) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation is Any:
        _validate_json_compatible(value, field_path)
        return value

    if origin in (Union, UnionType):
        if value is None and type(None) in args:
            return None
        errors = []
        for option in args:
            if option is type(None):
                continue
            try:
                return _coerce_value(value, option, field_path)
            except SchemaValidationError as exc:
                errors.append(str(exc))
        raise SchemaValidationError(f"{field_path} does not match any allowed type: {'; '.join(errors)}")

    if origin is list:
        if not isinstance(value, list):
            raise SchemaValidationError(f"{field_path} must be a list")
        item_type = args[0] if args else Any
        return [_coerce_value(item, item_type, f"{field_path}[{index}]") for index, item in enumerate(value)]

    if origin is dict:
        if not isinstance(value, dict):
            raise SchemaValidationError(f"{field_path} must be a mapping")
        key_type = args[0] if args else str
        value_type = args[1] if len(args) > 1 else Any
        coerced: dict[Any, Any] = {}
        for key, item in value.items():
            coerced_key = _coerce_value(key, key_type, f"{field_path}.key")
            coerced[coerced_key] = _coerce_value(item, value_type, f"{field_path}.{key}")
        return coerced

    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return _coerce_enum(annotation, value, field_path)

    if isinstance(annotation, type) and issubclass(annotation, SchemaModel):
        if isinstance(value, annotation):
            return value
        if isinstance(value, Mapping):
            return annotation.from_dict(value)
        raise SchemaValidationError(f"{field_path} must be a mapping or {annotation.__name__}")

    if annotation is str:
        if not isinstance(value, str):
            raise SchemaValidationError(f"{field_path} must be a string")
        return value

    if annotation is bool:
        if type(value) is not bool:
            raise SchemaValidationError(f"{field_path} must be a boolean")
        return value

    if annotation is int:
        if type(value) is not int:
            raise SchemaValidationError(f"{field_path} must be an integer")
        return value

    if annotation is float:
        if type(value) not in (int, float):
            raise SchemaValidationError(f"{field_path} must be a number")
        value = float(value)
        if not isfinite(value):
            raise SchemaValidationError(f"{field_path} must be finite")
        return value

    _validate_json_compatible(value, field_path)
    return value


def _coerce_enum(enum_type: type[StrEnum], value: Any, field_name: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise SchemaValidationError(f"{field_name} must be one of: {allowed}") from exc


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, SchemaModel):
        return value.to_dict()
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    return value


def _validate_json_compatible(value: Any, field_name: str) -> None:
    if value is None or isinstance(value, str) or type(value) in (bool, int):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise SchemaValidationError(f"{field_name} must be JSON-compatible")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_compatible(item, f"{field_name}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SchemaValidationError(f"{field_name} keys must be strings")
            _validate_json_compatible(item, f"{field_name}.{key}")
        return
    raise SchemaValidationError(f"{field_name} must be JSON-compatible")


def _require_non_empty_str(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")


def _validate_optional_str(value: str | None, field_name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")


def _require_non_empty_list(value: list[Any], field_name: str) -> None:
    if not isinstance(value, list) or not value:
        raise SchemaValidationError(f"{field_name} must be a non-empty list")


def _validate_id_list(value: list[str], field_name: str, *, require_non_empty: bool = False) -> None:
    if require_non_empty:
        _require_non_empty_list(value, field_name)
    elif not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list")
    for index, item in enumerate(value):
        _require_non_empty_str(item, f"{field_name}[{index}]")
    _reject_duplicate_values(value, field_name)


def _validate_model_list(value: list[Any], model_type: type[SchemaModel], field_name: str) -> None:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list")
    for index, item in enumerate(value):
        if not isinstance(item, model_type):
            raise SchemaValidationError(f"{field_name}[{index}] must be {model_type.__name__}")


def _validate_source_refs(
    value: list["SourceRef"] | None,
    field_name: str,
    *,
    require_non_empty: bool = False,
    require_chunk_id: bool = False,
) -> None:
    if value is None:
        if require_non_empty:
            raise SchemaValidationError(f"{field_name} must be a non-empty list")
        return
    _validate_model_list(value, SourceRef, field_name)
    if require_non_empty and not value:
        raise SchemaValidationError(f"{field_name} must be a non-empty list")
    if require_chunk_id:
        for index, source_ref in enumerate(value):
            if not source_ref.chunk_id:
                raise SchemaValidationError(f"{field_name}[{index}].chunk_id is required")


def _reject_duplicate_values(values: list[str], field_name: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise SchemaValidationError(f"{field_name} contains duplicate value: {value}")
        seen.add(value)


def _reject_duplicate_ids(items: list[Any], id_attr: str, field_name: str) -> None:
    seen: set[str] = set()
    for item in items:
        value = getattr(item, id_attr)
        if value in seen:
            raise SchemaValidationError(f"{field_name} contains duplicate {id_attr}: {value}")
        seen.add(value)


def _validate_count_map(value: dict[str, Any], field_name: str) -> None:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{field_name} must be a mapping")
    for key, count in value.items():
        _require_non_empty_str(key, f"{field_name}.key")
        if type(count) is not int or count < 0:
            raise SchemaValidationError(f"{field_name}.{key} must be a zero or positive integer")


def _validate_artifact_path_map(value: dict[str, str], project_id: str, run_id: str) -> None:
    expected_prefix = f"artifacts/{project_id}/{run_id}/"
    for key, path in value.items():
        _require_non_empty_str(key, "artifact_paths.key")
        _require_non_empty_str(path, f"artifact_paths.{key}")
        if not path.startswith(expected_prefix):
            raise SchemaValidationError(f"artifact_paths.{key} must start with {expected_prefix}")


@dataclass
class ProjectConfig(SchemaModel):
    project_id: str
    bot_name: str
    target_url: str
    coverage_policy: dict[str, Any]
    approval_policy: dict[str, Any]
    description: str | None = None
    source_paths: list[str] | None = None
    artifact_root: str | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.project_id, "project_id")
        _require_non_empty_str(self.bot_name, "bot_name")
        _require_non_empty_str(self.target_url, "target_url")
        _validate_json_compatible(self.coverage_policy, "coverage_policy")
        _validate_json_compatible(self.approval_policy, "approval_policy")
        if self.source_paths is not None:
            _validate_id_list(self.source_paths, "source_paths")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class Document(SchemaModel):
    document_id: str
    project_id: str
    source_path: str
    title: str
    content_checksum: str
    ingestion_status: DocumentIngestionStatus
    content_type: str | None = None
    size_bytes: int | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        self.ingestion_status = _coerce_enum(DocumentIngestionStatus, self.ingestion_status, "ingestion_status")
        _require_non_empty_str(self.document_id, "document_id")
        _require_non_empty_str(self.project_id, "project_id")
        _require_non_empty_str(self.source_path, "source_path")
        _require_non_empty_str(self.title, "title")
        _require_non_empty_str(self.content_checksum, "content_checksum")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise SchemaValidationError("size_bytes must be zero or positive")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class SourceRef(SchemaModel):
    document_id: str
    chunk_id: str | None = None
    location: str | None = None
    quote: str | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.document_id, "document_id")
        if self.chunk_id is not None:
            _require_non_empty_str(self.chunk_id, "chunk_id")
        _validate_optional_str(self.location, "location")
        _validate_optional_str(self.quote, "quote")


@dataclass
class SourceChunk(SchemaModel):
    chunk_id: str
    document_id: str
    text: str
    checksum: str
    processing_status: SourceChunkProcessingStatus
    sequence: int | None = None
    location: str | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        self.processing_status = _coerce_enum(
            SourceChunkProcessingStatus, self.processing_status, "processing_status"
        )
        _require_non_empty_str(self.chunk_id, "chunk_id")
        _require_non_empty_str(self.document_id, "document_id")
        _require_non_empty_str(self.text, "text")
        _require_non_empty_str(self.checksum, "checksum")
        if self.sequence is not None and self.sequence < 0:
            raise SchemaValidationError("sequence must be zero or positive")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class SourcePackage(SchemaModel):
    source_package_id: str
    project_id: str
    document_ids: list[str]
    chunks: list[SourceChunk]
    checksum: str
    created_at: str | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.source_package_id, "source_package_id")
        _require_non_empty_str(self.project_id, "project_id")
        _validate_id_list(self.document_ids, "document_ids", require_non_empty=True)
        _validate_model_list(self.chunks, SourceChunk, "chunks")
        _require_non_empty_list(self.chunks, "chunks")
        _reject_duplicate_ids(self.chunks, "chunk_id", "chunks")
        _require_non_empty_str(self.checksum, "checksum")
        document_ids = set(self.document_ids)
        for chunk in self.chunks:
            if chunk.document_id not in document_ids:
                raise SchemaValidationError("chunks must reference document_ids")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class CandidateRequirement(SchemaModel):
    candidate_id: str
    statement: str
    requirement_type_guess: str
    source_refs: list[SourceRef]
    confidence: float
    rationale: str | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.candidate_id, "candidate_id")
        _require_non_empty_str(self.statement, "statement")
        _require_non_empty_str(self.requirement_type_guess, "requirement_type_guess")
        _validate_source_refs(self.source_refs, "source_refs", require_non_empty=True, require_chunk_id=True)
        if self.confidence < 0 or self.confidence > 1:
            raise SchemaValidationError("confidence must be between 0 and 1 inclusive")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class CandidateRequirementPackage(SchemaModel):
    candidate_package_id: str
    project_id: str
    source_package_id: str
    candidates: list[CandidateRequirement]
    skill_run_ids: list[str] | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.candidate_package_id, "candidate_package_id")
        _require_non_empty_str(self.project_id, "project_id")
        _require_non_empty_str(self.source_package_id, "source_package_id")
        _validate_model_list(self.candidates, CandidateRequirement, "candidates")
        _reject_duplicate_ids(self.candidates, "candidate_id", "candidates")
        if self.skill_run_ids is not None:
            _validate_id_list(self.skill_run_ids, "skill_run_ids")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class AtomicRequirement(SchemaModel):
    requirement_id: str
    statement: str
    requirement_type: str
    status: AtomicRequirementStatus
    origin: RequirementOrigin
    source_refs: list[SourceRef] | None = None
    candidate_ids: list[str] | None = None
    approval_required: bool | None = None
    approval_status: str | None = None
    duplicate_of: str | None = None
    conflicts_with: list[str] | None = None
    rationale: str | None = None
    metadata: dict[str, Any] | None = None

    @property
    def requires_approval_before_export(self) -> bool:
        return self.origin in NON_SOURCE_REQUIREMENT_ORIGINS

    @property
    def is_eligible_for_obligation_planning(self) -> bool:
        if self.status != AtomicRequirementStatus.VALIDATED:
            return False
        if self.origin == RequirementOrigin.SOURCE_DERIVED:
            return bool(self.source_refs)
        return self.approval_required is True and self.approval_status == "approved"

    def _validate(self) -> None:
        self.status = _coerce_enum(AtomicRequirementStatus, self.status, "status")
        self.origin = _coerce_enum(RequirementOrigin, self.origin, "origin")
        _require_non_empty_str(self.requirement_id, "requirement_id")
        _require_non_empty_str(self.statement, "statement")
        _require_non_empty_str(self.requirement_type, "requirement_type")
        if self.status == AtomicRequirementStatus.INFERRED and self.origin != RequirementOrigin.INFERRED:
            raise SchemaValidationError("status=inferred is only allowed with origin=inferred")
        if self.origin == RequirementOrigin.SOURCE_DERIVED:
            _validate_source_refs(self.source_refs, "source_refs", require_non_empty=True, require_chunk_id=True)
        else:
            _validate_source_refs(self.source_refs, "source_refs", require_chunk_id=True)
            if self.approval_required is not True:
                raise SchemaValidationError("approval_required must be true for non-source requirement origins")
        if self.candidate_ids is not None:
            _validate_id_list(self.candidate_ids, "candidate_ids")
        if self.conflicts_with is not None:
            _validate_id_list(self.conflicts_with, "conflicts_with")
        if self.duplicate_of is not None:
            _require_non_empty_str(self.duplicate_of, "duplicate_of")
        if self.approval_status is not None:
            _require_non_empty_str(self.approval_status, "approval_status")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class AtomicRequirementLedger(SchemaModel):
    atomic_ledger_id: str
    project_id: str
    candidate_package_id: str
    requirements: list[AtomicRequirement]
    skill_run_ids: list[str] | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.atomic_ledger_id, "atomic_ledger_id")
        _require_non_empty_str(self.project_id, "project_id")
        _require_non_empty_str(self.candidate_package_id, "candidate_package_id")
        _validate_model_list(self.requirements, AtomicRequirement, "requirements")
        _reject_duplicate_ids(self.requirements, "requirement_id", "requirements")
        if self.skill_run_ids is not None:
            _validate_id_list(self.skill_run_ids, "skill_run_ids")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class GovernedRequirementLedger(SchemaModel):
    governed_ledger_id: str
    project_id: str
    atomic_ledger_id: str
    requirements: list[AtomicRequirement]
    governance_summary: dict[str, int]
    policy_version: str | None = None
    skill_run_ids: list[str] | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.governed_ledger_id, "governed_ledger_id")
        _require_non_empty_str(self.project_id, "project_id")
        _require_non_empty_str(self.atomic_ledger_id, "atomic_ledger_id")
        _validate_model_list(self.requirements, AtomicRequirement, "requirements")
        _reject_duplicate_ids(self.requirements, "requirement_id", "requirements")
        _validate_count_map(self.governance_summary, "governance_summary")
        for requirement in self.requirements:
            if requirement.status == AtomicRequirementStatus.DUPLICATE and not requirement.duplicate_of:
                raise SchemaValidationError("duplicate requirements must identify duplicate_of")
        if self.skill_run_ids is not None:
            _validate_id_list(self.skill_run_ids, "skill_run_ids")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class TestObligation(SchemaModel):
    obligation_id: str
    requirement_id: str
    obligation_type: str
    status: TestObligationStatus
    source_refs: list[SourceRef]
    description: str | None = None
    coverage_intent: str | None = None
    blocked_reason: str | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        self.status = _coerce_enum(TestObligationStatus, self.status, "status")
        _require_non_empty_str(self.obligation_id, "obligation_id")
        _require_non_empty_str(self.requirement_id, "requirement_id")
        _require_non_empty_str(self.obligation_type, "obligation_type")
        _validate_source_refs(self.source_refs, "source_refs", require_chunk_id=True)
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class TestObligationLedger(SchemaModel):
    obligation_ledger_id: str
    project_id: str
    governed_ledger_id: str
    obligations: list[TestObligation]
    coverage_policy_snapshot: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.obligation_ledger_id, "obligation_ledger_id")
        _require_non_empty_str(self.project_id, "project_id")
        _require_non_empty_str(self.governed_ledger_id, "governed_ledger_id")
        _validate_model_list(self.obligations, TestObligation, "obligations")
        _reject_duplicate_ids(self.obligations, "obligation_id", "obligations")
        if self.coverage_policy_snapshot is not None:
            _validate_json_compatible(self.coverage_policy_snapshot, "coverage_policy_snapshot")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class ConversationTurn(SchemaModel):
    turn_id: str
    speaker: ConversationSpeaker
    text: str
    expected_intent: str | None = None
    expected_state: str | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        self.speaker = _coerce_enum(ConversationSpeaker, self.speaker, "speaker")
        _require_non_empty_str(self.turn_id, "turn_id")
        _require_non_empty_str(self.text, "text")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class Assertion(SchemaModel):
    assertion_id: str
    assertion_type: str
    target: str
    expected: Any
    severity: str | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.assertion_id, "assertion_id")
        _require_non_empty_str(self.assertion_type, "assertion_type")
        _require_non_empty_str(self.target, "target")
        _validate_json_compatible(self.expected, "expected")
        if isinstance(self.expected, str):
            _require_non_empty_str(self.expected, "expected")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class TestCase(SchemaModel):
    test_case_id: str
    title: str
    status: TestCaseStatus
    requirement_ids: list[str]
    obligation_ids: list[str]
    turns: list[ConversationTurn]
    assertions: list[Assertion]
    source_refs: list[SourceRef] | None = None
    priority: str | None = None
    tags: list[str] | None = None
    export_eligible: bool | None = None
    rejection_reasons: list[str] | None = None
    metadata: dict[str, Any] | None = None

    @property
    def is_exportable(self) -> bool:
        return (
            self.export_eligible is True
            and self.status in EXPORTABLE_TEST_STATUSES
            and bool(self.source_refs)
        )

    def _validate(self) -> None:
        self.status = _coerce_enum(TestCaseStatus, self.status, "status")
        _require_non_empty_str(self.test_case_id, "test_case_id")
        _require_non_empty_str(self.title, "title")
        _validate_id_list(self.requirement_ids, "requirement_ids", require_non_empty=True)
        _validate_id_list(self.obligation_ids, "obligation_ids", require_non_empty=True)
        _validate_model_list(self.turns, ConversationTurn, "turns")
        _reject_duplicate_ids(self.turns, "turn_id", "turns")
        _validate_model_list(self.assertions, Assertion, "assertions")
        _reject_duplicate_ids(self.assertions, "assertion_id", "assertions")
        if self.status in EXPORTABLE_TEST_STATUSES or self.export_eligible is True:
            _validate_source_refs(self.source_refs, "source_refs", require_non_empty=True, require_chunk_id=True)
        else:
            _validate_source_refs(self.source_refs, "source_refs", require_chunk_id=True)
        if self.tags is not None:
            _validate_id_list(self.tags, "tags")
        if self.rejection_reasons is not None:
            _validate_id_list(self.rejection_reasons, "rejection_reasons")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class DraftTestSuite(SchemaModel):
    draft_suite_id: str
    project_id: str
    obligation_ledger_id: str
    test_cases: list[TestCase]
    skill_run_ids: list[str] | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.draft_suite_id, "draft_suite_id")
        _require_non_empty_str(self.project_id, "project_id")
        _require_non_empty_str(self.obligation_ledger_id, "obligation_ledger_id")
        _validate_model_list(self.test_cases, TestCase, "test_cases")
        _reject_duplicate_ids(self.test_cases, "test_case_id", "test_cases")
        if self.skill_run_ids is not None:
            _validate_id_list(self.skill_run_ids, "skill_run_ids")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class ValidatedTestSuite(SchemaModel):
    validated_suite_id: str
    project_id: str
    draft_suite_id: str
    test_cases: list[TestCase]
    validation_summary: dict[str, int]
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.validated_suite_id, "validated_suite_id")
        _require_non_empty_str(self.project_id, "project_id")
        _require_non_empty_str(self.draft_suite_id, "draft_suite_id")
        _validate_model_list(self.test_cases, TestCase, "test_cases")
        _reject_duplicate_ids(self.test_cases, "test_case_id", "test_cases")
        _validate_count_map(self.validation_summary, "validation_summary")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class CoverageReport(SchemaModel):
    coverage_report_id: str
    project_id: str
    validated_suite_id: str
    requirement_counts: dict[str, int]
    obligation_counts: dict[str, int]
    test_counts: dict[str, int]
    source_chunk_counts: dict[str, int]
    uncovered_requirement_ids: list[str] | None = None
    uncovered_obligation_ids: list[str] | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.coverage_report_id, "coverage_report_id")
        _require_non_empty_str(self.project_id, "project_id")
        _require_non_empty_str(self.validated_suite_id, "validated_suite_id")
        _validate_count_map(self.requirement_counts, "requirement_counts")
        _validate_count_map(self.obligation_counts, "obligation_counts")
        _validate_count_map(self.test_counts, "test_counts")
        _validate_count_map(self.source_chunk_counts, "source_chunk_counts")
        if self.uncovered_requirement_ids is not None:
            _validate_id_list(self.uncovered_requirement_ids, "uncovered_requirement_ids")
        if self.uncovered_obligation_ids is not None:
            _validate_id_list(self.uncovered_obligation_ids, "uncovered_obligation_ids")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class ReviewReportMetadata(SchemaModel):
    review_report_id: str
    project_id: str
    governed_ledger_id: str
    obligation_ledger_id: str
    validated_suite_id: str
    coverage_report_id: str
    report_path: str
    generated_at: str | None = None
    summary: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.review_report_id, "review_report_id")
        _require_non_empty_str(self.project_id, "project_id")
        _require_non_empty_str(self.governed_ledger_id, "governed_ledger_id")
        _require_non_empty_str(self.obligation_ledger_id, "obligation_ledger_id")
        _require_non_empty_str(self.validated_suite_id, "validated_suite_id")
        _require_non_empty_str(self.coverage_report_id, "coverage_report_id")
        _require_non_empty_str(self.report_path, "report_path")
        if self.summary is not None:
            _validate_json_compatible(self.summary, "summary")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class ExecutorExportPackage(SchemaModel):
    export_package_id: str
    project_id: str
    validated_suite_id: str
    exported_test_case_ids: list[str]
    format: str
    output_paths: list[str]
    eligibility_summary: dict[str, int]
    generated_at: str | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.export_package_id, "export_package_id")
        _require_non_empty_str(self.project_id, "project_id")
        _require_non_empty_str(self.validated_suite_id, "validated_suite_id")
        _validate_id_list(self.exported_test_case_ids, "exported_test_case_ids")
        _require_non_empty_str(self.format, "format")
        _validate_id_list(self.output_paths, "output_paths", require_non_empty=True)
        _validate_count_map(self.eligibility_summary, "eligibility_summary")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class SkillDefinition(SchemaModel):
    skill_id: str
    name: str
    version: str
    input_contract: str
    output_contract: str
    entrypoint: str
    description: str | None = None
    timeout_seconds: int | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        _require_non_empty_str(self.skill_id, "skill_id")
        _require_non_empty_str(self.name, "name")
        _require_non_empty_str(self.version, "version")
        _require_non_empty_str(self.input_contract, "input_contract")
        _require_non_empty_str(self.output_contract, "output_contract")
        _require_non_empty_str(self.entrypoint, "entrypoint")
        if self.timeout_seconds is not None and self.timeout_seconds < 0:
            raise SchemaValidationError("timeout_seconds must be zero or positive")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class SkillRunRecord(SchemaModel):
    skill_run_id: str
    skill_id: str
    status: SkillRunStatus
    input_artifact_paths: list[str]
    output_artifact_paths: list[str]
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    metadata: dict[str, Any] | None = None

    def _validate(self) -> None:
        self.status = _coerce_enum(SkillRunStatus, self.status, "status")
        _require_non_empty_str(self.skill_run_id, "skill_run_id")
        _require_non_empty_str(self.skill_id, "skill_id")
        _validate_id_list(self.input_artifact_paths, "input_artifact_paths")
        _validate_id_list(self.output_artifact_paths, "output_artifact_paths")
        if self.status == SkillRunStatus.FAILED and not self.error:
            raise SchemaValidationError("failed skill runs must include an error")
        if self.error is not None:
            _require_non_empty_str(self.error, "error")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")


@dataclass
class PipelineRunState(SchemaModel):
    pipeline_run_id: str
    project_id: str
    run_id: str
    status: PipelineRunStatus
    current_stage: str
    artifact_paths: dict[str, str]
    completed_stages: list[str] | None = None
    failed_stage: str | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] | None = None

    _runtime_stage_order: ClassVar[dict[str, int]] = {
        stage: index for index, stage in enumerate(PIPELINE_RUN_STAGES)
    }

    def _validate(self) -> None:
        self.status = _coerce_enum(PipelineRunStatus, self.status, "status")
        _require_non_empty_str(self.pipeline_run_id, "pipeline_run_id")
        _require_non_empty_str(self.project_id, "project_id")
        _require_non_empty_str(self.run_id, "run_id")
        _require_non_empty_str(self.current_stage, "current_stage")
        if self.current_stage not in KNOWN_COMPONENT_STAGES:
            raise SchemaValidationError("current_stage must be a known component or pipeline stage")
        _validate_artifact_path_map(self.artifact_paths, self.project_id, self.run_id)
        if self.completed_stages is not None:
            _validate_id_list(self.completed_stages, "completed_stages")
            for stage in self.completed_stages:
                if stage not in KNOWN_COMPONENT_STAGES:
                    raise SchemaValidationError("completed_stages must contain known stages")
            runtime_completed = [
                stage for stage in self.completed_stages if stage in self._runtime_stage_order
            ]
            expected_prefix = PIPELINE_RUN_STAGES[: len(runtime_completed)]
            if runtime_completed != expected_prefix:
                raise SchemaValidationError("completed_stages must not skip required prior stages")
        if self.failed_stage is not None and self.failed_stage not in KNOWN_COMPONENT_STAGES:
            raise SchemaValidationError("failed_stage must be a known component or pipeline stage")
        if self.error is not None:
            _require_non_empty_str(self.error, "error")
        if self.metadata is not None:
            _validate_json_compatible(self.metadata, "metadata")
