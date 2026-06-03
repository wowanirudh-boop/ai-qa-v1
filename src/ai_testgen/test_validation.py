from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_testgen.artifact_store import ArtifactStore, ArtifactStoreError
from ai_testgen.coverage import build_coverage_report
from ai_testgen.obligation_planning import TEST_OBLIGATION_LEDGER_ARTIFACT_NAME, TEST_OBLIGATIONS_STAGE
from ai_testgen.requirement_governance import (
    GOVERNED_REQUIREMENT_LEDGER_ARTIFACT_NAME,
    GOVERNED_REQUIREMENTS_STAGE,
)
from ai_testgen.schemas import (
    AtomicRequirement,
    AtomicRequirementStatus,
    CoverageReport,
    DraftTestSuite,
    GovernedRequirementLedger,
    SchemaModel,
    SchemaValidationError,
    SourcePackage,
    SourceRef,
    TestCase,
    TestCaseStatus,
    TestObligation,
    TestObligationLedger,
    TestObligationStatus,
    ValidatedTestSuite,
)
from ai_testgen.source_ledger import SOURCE_PACKAGE_ARTIFACT_NAME, SOURCE_PACKAGE_STAGE
from ai_testgen.validators import validate_obligation_links


DRAFT_TESTS_STAGE = "07_draft_tests"
DRAFT_TEST_SUITE_ARTIFACT_NAME = "draft_test_suite"
VALIDATED_TESTS_STAGE = "08_validated_tests"
VALIDATED_TEST_SUITE_ARTIFACT_NAME = "validated_test_suite"
COVERAGE_REPORT_ARTIFACT_NAME = "coverage_report"
VALIDATED_SUITE_ID = "validated_suite_001"
NORMAL_TESTABLE_OBLIGATION_STATUSES = {
    TestObligationStatus.PLANNED,
    TestObligationStatus.GENERATED,
    TestObligationStatus.COVERED,
}
ENTITY_DATA_OBLIGATION_TYPES = {
    "positive",
    "provided_entity",
    "api_success",
}
API_SETUP_OBLIGATION_TYPES = {
    "api_success",
    "api_error",
}
ENTITY_METADATA_KEYS = {
    "required_entity",
    "required_entities",
    "supported_entity",
    "supported_entities",
    "allowed_entity",
    "allowed_entities",
    "entity",
    "entities",
    "input_entity",
    "input_entities",
}
ENTITY_FORMAT_METADATA_KEYS = {
    "format",
    "expected_format",
    "validation",
    "validation_rule",
    "validation_rules",
    "pattern",
    "value_format",
}
SCHEMA_CONTEXT_CUES = {
    "api",
    "schema",
    "payload",
    "contract",
    "response",
    "body",
    "field",
    "fields",
    "object",
    "nullable",
    "nullability",
    "type",
    "maxlength",
    "required",
    "returned",
    "returns",
}
GENERIC_SCHEMA_DIALOGUE_TERMS = {
    "schema",
    "field",
    "fields",
    "response",
    "returned",
    "payload",
    "object",
    "nullable",
    "nullability",
    "type",
    "maxlength",
    "required",
    "array",
    "string",
    "boolean",
    "integer",
}
ENTITY_COLLECTION_CUES = {
    "ask",
    "asks",
    "collect",
    "collects",
    "accept",
    "accepts",
    "require",
    "requires",
    "provide",
    "enter",
    "entering",
    "share",
    "give",
    "type",
    "input",
    "send",
    "tell",
}
CHATBOT_COLLECTION_SUPPORT_CUES = {
    "bot",
    "chatbot",
    "assistant",
    "user",
    "users",
    "customer",
    "customers",
    "self service",
    "selfserve",
    "self serve",
}


class TestValidationError(Exception):
    """Base error for C12 test validation and coverage failures."""


class DraftTestSuiteArtifactError(TestValidationError):
    """Raised when the input DraftTestSuite artifact path cannot be used."""


class InvalidTestValidationInputError(TestValidationError):
    """Raised when C12 input artifacts fail schema or cross-artifact validation."""


class InvalidValidatedTestSuiteError(TestValidationError):
    """Raised when generated C12 output fails validation."""


class TestValidationPersistenceError(TestValidationError):
    """Raised when C12 cannot persist its output artifacts."""


@dataclass(frozen=True)
class TestValidationResult:
    validated_suite: ValidatedTestSuite
    coverage_report: CoverageReport
    validated_suite_path: Path | None = None
    coverage_report_path: Path | None = None


@dataclass(frozen=True)
class EntitySpec:
    name: str
    aliases: tuple[str, ...]
    format_text: str = ""


def validate_tests_from_draft_suite_artifact(
    draft_suite_path: str | Path,
) -> TestValidationResult:
    draft_path = Path(draft_suite_path)
    artifact_root, project_id, run_id = _artifact_context_from_draft_suite_path(draft_path)
    store = ArtifactStore(artifact_root)

    draft_suite = _load_draft_suite(store, project_id=project_id, run_id=run_id)
    if draft_suite.project_id != project_id:
        raise DraftTestSuiteArtifactError(
            f"DraftTestSuite artifact project directory must match project_id "
            f"{draft_suite.project_id}: {draft_path}"
        )
    governed_ledger = _load_governed_ledger(store, project_id=project_id, run_id=run_id)
    obligation_ledger = _load_obligation_ledger(store, project_id=project_id, run_id=run_id)
    source_package = _load_source_package_if_present(store, project_id=project_id, run_id=run_id)

    result = validate_draft_suite(
        draft_suite,
        governed_ledger,
        obligation_ledger,
        source_package,
    )
    validated_artifact = _write_validated_suite(store, run_id=run_id, suite=result.validated_suite)
    coverage_artifact = _write_coverage_report(store, run_id=run_id, report=result.coverage_report)
    return TestValidationResult(
        validated_suite=result.validated_suite,
        coverage_report=result.coverage_report,
        validated_suite_path=validated_artifact.path,
        coverage_report_path=coverage_artifact.path,
    )


def validate_draft_suite(
    draft_suite: DraftTestSuite | Mapping[str, Any],
    governed_ledger: GovernedRequirementLedger | Mapping[str, Any],
    obligation_ledger: TestObligationLedger | Mapping[str, Any],
    source_package: SourcePackage | Mapping[str, Any] | None = None,
) -> TestValidationResult:
    try:
        draft = _coerce_model(DraftTestSuite, draft_suite)
        governed = _coerce_model(GovernedRequirementLedger, governed_ledger)
        obligations = _coerce_model(TestObligationLedger, obligation_ledger)
        sources = _coerce_optional_model(SourcePackage, source_package)
    except SchemaValidationError as exc:
        raise InvalidTestValidationInputError(str(exc)) from exc

    _validate_input_links(draft, governed, obligations, sources)
    validated_cases = _validated_test_cases(draft.test_cases, governed, obligations, sources)
    summary = _validation_summary(validated_cases)

    try:
        validated_suite = ValidatedTestSuite.from_dict(
            {
                "validated_suite_id": VALIDATED_SUITE_ID,
                "project_id": draft.project_id,
                "draft_suite_id": draft.draft_suite_id,
                "test_cases": [test_case.to_dict() for test_case in validated_cases],
                "validation_summary": summary,
            }
        )
        coverage_report = build_coverage_report(
            validated_suite,
            governed,
            obligations,
            sources,
        )
    except SchemaValidationError as exc:
        raise InvalidValidatedTestSuiteError(f"Invalid C12 output: {exc}") from exc

    return TestValidationResult(
        validated_suite=validated_suite,
        coverage_report=coverage_report,
    )


def _coerce_model(model_type: type[SchemaModel], value: SchemaModel | Mapping[str, Any]) -> Any:
    if isinstance(value, model_type):
        return value
    if isinstance(value, Mapping):
        return model_type.from_dict(value)
    raise SchemaValidationError(f"{model_type.__name__} input must be a mapping or model")


def _coerce_optional_model(
    model_type: type[SchemaModel],
    value: SchemaModel | Mapping[str, Any] | None,
) -> Any:
    if value is None:
        return None
    return _coerce_model(model_type, value)


def _validate_input_links(
    draft_suite: DraftTestSuite,
    governed_ledger: GovernedRequirementLedger,
    obligation_ledger: TestObligationLedger,
    source_package: SourcePackage | None,
) -> None:
    if draft_suite.project_id != governed_ledger.project_id:
        raise InvalidTestValidationInputError("DraftTestSuite project_id must match GovernedRequirementLedger")
    if draft_suite.project_id != obligation_ledger.project_id:
        raise InvalidTestValidationInputError("DraftTestSuite project_id must match TestObligationLedger")
    if draft_suite.obligation_ledger_id != obligation_ledger.obligation_ledger_id:
        raise InvalidTestValidationInputError("DraftTestSuite obligation_ledger_id must match TestObligationLedger")
    if obligation_ledger.governed_ledger_id != governed_ledger.governed_ledger_id:
        raise InvalidTestValidationInputError("TestObligationLedger governed_ledger_id must match GovernedRequirementLedger")
    if source_package is not None and source_package.project_id != draft_suite.project_id:
        raise InvalidTestValidationInputError("SourcePackage project_id must match DraftTestSuite")

    try:
        validate_obligation_links(obligation_ledger.obligations, governed_ledger.requirements)
    except SchemaValidationError as exc:
        raise InvalidTestValidationInputError(str(exc)) from exc


def _validated_test_cases(
    test_cases: list[TestCase],
    governed_ledger: GovernedRequirementLedger,
    obligation_ledger: TestObligationLedger,
    source_package: SourcePackage | None,
) -> list[TestCase]:
    requirements_by_id = {
        requirement.requirement_id: requirement
        for requirement in governed_ledger.requirements
    }
    obligations_by_id = {
        obligation.obligation_id: obligation
        for obligation in obligation_ledger.obligations
    }
    seen_duplicate_keys: set[tuple[Any, ...]] = set()
    seen_near_duplicate_keys: set[tuple[Any, ...]] = set()
    validated_cases: list[TestCase] = []

    for test_case in test_cases:
        reasons: list[str] = []
        hard_rejection = False

        duplicate_key = _duplicate_key(test_case)
        if duplicate_key in seen_duplicate_keys:
            _add_reason(reasons, "duplicate test case content")
            hard_rejection = True
        else:
            seen_duplicate_keys.add(duplicate_key)
            near_duplicate_key = _near_duplicate_key(test_case)
            if near_duplicate_key in seen_near_duplicate_keys:
                _add_reason(reasons, "near-duplicate test case content")
                hard_rejection = True
            else:
                seen_near_duplicate_keys.add(near_duplicate_key)

        linked_requirements = _linked_requirements(test_case, requirements_by_id, reasons)
        linked_obligations = _linked_obligations(test_case, obligations_by_id, reasons)
        if len(linked_requirements) != len(test_case.requirement_ids):
            hard_rejection = True
        if len(linked_obligations) != len(test_case.obligation_ids):
            hard_rejection = True

        if linked_obligations:
            expected_requirement_ids = _requirement_ids_for_obligations(linked_obligations)
            if set(test_case.requirement_ids) != set(expected_requirement_ids):
                _add_reason(reasons, "requirement_ids do not match linked obligations")
                hard_rejection = True

        for requirement in linked_requirements:
            if requirement.status == AtomicRequirementStatus.REJECTED:
                _add_reason(reasons, f"rejected requirement {requirement.requirement_id}")
                hard_rejection = True
            elif requirement.status == AtomicRequirementStatus.CONFLICTING:
                _add_reason(reasons, f"conflicting requirement {requirement.requirement_id}")
            elif requirement.status != AtomicRequirementStatus.VALIDATED:
                _add_reason(reasons, f"non-exportable requirement {requirement.requirement_id}")
            elif requirement.requires_approval_before_export and requirement.approval_status != "approved":
                _add_reason(reasons, f"unapproved non-source requirement {requirement.requirement_id}")

        for obligation in linked_obligations:
            if obligation.status == TestObligationStatus.REJECTED:
                _add_reason(reasons, f"rejected obligation {obligation.obligation_id}")
                hard_rejection = True
            elif _is_non_chatbot_api_schema_obligation(obligation):
                _add_reason(reasons, f"non-chatbot API-schema obligation {obligation.obligation_id}")
            elif obligation.status not in NORMAL_TESTABLE_OBLIGATION_STATUSES:
                _add_reason(reasons, f"non-exportable obligation {obligation.obligation_id}")

        if not test_case.source_refs:
            _add_reason(reasons, "missing source_refs")
        elif linked_obligations:
            expected_refs = _source_refs_for_obligations(linked_obligations)
            if _normalized_source_refs(test_case.source_refs) != _normalized_source_refs(expected_refs):
                _add_reason(reasons, "source_refs do not match linked obligations")

        for reason in _semantic_validation_reasons(
            test_case,
            linked_requirements,
            linked_obligations,
            source_package,
        ):
            _add_reason(reasons, reason)

        if hard_rejection:
            status = TestCaseStatus.REJECTED
            export_eligible = False
        elif reasons:
            status = TestCaseStatus.NEEDS_REVIEW
            export_eligible = False
        else:
            status = TestCaseStatus.VALID
            export_eligible = True

        data = test_case.to_dict()
        data["status"] = status.value
        data["export_eligible"] = export_eligible
        if reasons:
            data["rejection_reasons"] = reasons
        else:
            data.pop("rejection_reasons", None)
        validated_cases.append(TestCase.from_dict(data))

    return validated_cases


def _linked_requirements(
    test_case: TestCase,
    requirements_by_id: dict[str, AtomicRequirement],
    reasons: list[str],
) -> list[AtomicRequirement]:
    linked: list[AtomicRequirement] = []
    for requirement_id in test_case.requirement_ids:
        requirement = requirements_by_id.get(requirement_id)
        if requirement is None:
            _add_reason(reasons, f"unknown requirement {requirement_id}")
        else:
            linked.append(requirement)
    return linked


def _linked_obligations(
    test_case: TestCase,
    obligations_by_id: dict[str, TestObligation],
    reasons: list[str],
) -> list[TestObligation]:
    linked: list[TestObligation] = []
    for obligation_id in test_case.obligation_ids:
        obligation = obligations_by_id.get(obligation_id)
        if obligation is None:
            _add_reason(reasons, f"unknown obligation {obligation_id}")
        else:
            linked.append(obligation)
    return linked


def _requirement_ids_for_obligations(obligations: Iterable[TestObligation]) -> list[str]:
    requirement_ids: list[str] = []
    for obligation in obligations:
        if obligation.requirement_id not in requirement_ids:
            requirement_ids.append(obligation.requirement_id)
    return requirement_ids


def _source_refs_for_obligations(obligations: Iterable[TestObligation]) -> list[SourceRef]:
    source_refs: list[SourceRef] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for obligation in obligations:
        for source_ref in obligation.source_refs:
            normalized = _normalized_source_ref(source_ref)
            if normalized not in seen:
                source_refs.append(source_ref)
                seen.add(normalized)
    return source_refs


def _normalized_source_refs(source_refs: Iterable[SourceRef] | None) -> list[tuple[tuple[str, Any], ...]]:
    return sorted(_normalized_source_ref(source_ref) for source_ref in (source_refs or []))


def _normalized_source_ref(source_ref: SourceRef) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted(source_ref.to_dict().items()))


def _duplicate_key(test_case: TestCase) -> tuple[Any, ...]:
    return (
        test_case.title.strip().lower(),
        tuple(sorted(test_case.requirement_ids)),
        tuple(sorted(test_case.obligation_ids)),
        tuple((turn.speaker.value, turn.text.strip().lower()) for turn in test_case.turns),
        tuple(
            (
                assertion.assertion_type.strip().lower(),
                assertion.target.strip().lower(),
                _json_stable_value(assertion.expected),
            )
            for assertion in test_case.assertions
        ),
    )


def _near_duplicate_key(test_case: TestCase) -> tuple[Any, ...]:
    return (
        tuple(sorted(test_case.requirement_ids)),
        tuple(sorted(test_case.obligation_ids)),
        tuple((turn.speaker.value, _semantic_text_key(turn.text)) for turn in test_case.turns),
        tuple(
            (
                _semantic_text_key(assertion.assertion_type),
                _semantic_text_key(assertion.target),
                _semantic_text_key(_text_value(assertion.expected)),
            )
            for assertion in test_case.assertions
        ),
    )


def _json_stable_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().lower()
    return repr(value)


def _semantic_validation_reasons(
    test_case: TestCase,
    linked_requirements: list[AtomicRequirement],
    linked_obligations: list[TestObligation],
    source_package: SourcePackage | None,
) -> list[str]:
    reasons: list[str] = []

    if _metadata_or_existing_reasons_flag_review(test_case):
        reasons.append("oracle flagged test for review")

    for turn in test_case.turns:
        if turn.speaker.value == "bot":
            if _is_raw_json_or_object_like_bot_turn(turn.text):
                reasons.append("raw API JSON bot turn")
            if _is_api_schema_dialogue(turn.text, linked_requirements, linked_obligations, source_package):
                reasons.append("API schema details in bot dialogue")
            if _is_descriptive_bot_turn(turn.text):
                reasons.append("descriptive bot turn")

    if _uses_unsupported_entity_collection(
        test_case,
        linked_requirements,
        linked_obligations,
        source_package,
    ):
        reasons.append("unsupported entity collection")

    if _has_unresolved_executable_placeholder(test_case):
        reasons.append("unresolved executable placeholder")

    entity_specs = _required_entity_specs(linked_requirements, linked_obligations, source_package)
    if entity_specs and not _has_valid_required_entity_data(test_case, entity_specs):
        reasons.append("invalid required entity test data")

    if _requires_api_setup(linked_obligations) and not _has_api_setup_or_stub_data(test_case):
        reasons.append("missing API setup or stub data")

    if source_package is not None and _has_unsupported_exact_wording_claim(
        test_case,
        linked_requirements,
        linked_obligations,
        source_package,
    ):
        reasons.append("exact wording is not supported by linked source")

    if any(_is_weak_or_meta_assertion(assertion) for assertion in test_case.assertions):
        reasons.append("weak or meta-level assertion")

    return reasons


def _is_non_chatbot_api_schema_obligation(obligation: TestObligation) -> bool:
    if obligation.obligation_type == "non_chatbot_api_schema":
        return True
    return bool(obligation.metadata and obligation.metadata.get("chatbot_obligation") is False)


def _is_raw_json_or_object_like_bot_turn(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[0] in "{[" and stripped[-1:] in "}]" and _loads_json_object_or_array(stripped):
        return True
    if stripped.startswith("{") and _generic_schema_term_count(stripped) >= 3 and stripped.count(":") >= 2:
        return True
    return False


def _loads_json_object_or_array(text: str) -> bool:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(value, (dict, list))


def _is_api_schema_dialogue(
    text: str,
    linked_requirements: list[AtomicRequirement],
    linked_obligations: list[TestObligation],
    source_package: SourcePackage | None,
) -> bool:
    normalized = _semantic_text_key(text)
    words = set(normalized.split())
    if not words:
        return False

    linked_schema_terms = _linked_schema_terms(linked_requirements, linked_obligations, source_package)
    linked_overlap = words & linked_schema_terms
    has_schema_cue = bool(words & GENERIC_SCHEMA_DIALOGUE_TERMS)
    if len(linked_overlap) >= 4 and has_schema_cue:
        return True

    return _generic_schema_term_count(normalized) >= 4 and has_schema_cue


def _generic_schema_term_count(text: str) -> int:
    words = set(_semantic_text_key(text).split())
    return sum(1 for term in GENERIC_SCHEMA_DIALOGUE_TERMS if term in words)


def _linked_schema_terms(
    linked_requirements: list[AtomicRequirement],
    linked_obligations: list[TestObligation],
    source_package: SourcePackage | None,
) -> set[str]:
    terms: set[str] = set()
    for sentence in _sentences(_linked_support_text(linked_requirements, linked_obligations, source_package)):
        normalized = _semantic_text_key(sentence)
        if not normalized:
            continue
        words = set(normalized.split())
        if not words & SCHEMA_CONTEXT_CUES:
            continue
        for word in words:
            if len(word) > 1:
                terms.add(word)
        for match in re.finditer(r"\b[A-Za-z][A-Za-z0-9_]*[A-Z_][A-Za-z0-9_]*\b", sentence):
            terms.add(_semantic_text_key(match.group(0)).replace(" ", ""))
    return terms


def _is_descriptive_bot_turn(text: str) -> bool:
    normalized = _semantic_text_key(text)
    descriptive_starts = (
        "bot asks",
        "bot should",
        "the bot should",
        "the chatbot should",
        "system displays",
        "assistant provides",
        "assistant should",
        "conversation ended",
    )
    if normalized.startswith(descriptive_starts):
        return True
    if normalized.startswith(("returns ", "assistant returns ", "system returns ")) and " details" in normalized:
        return True
    return normalized.startswith("the bot ") and any(
        cue in normalized
        for cue in (
            " should respond",
            " should ask",
            " provides ",
            " displays ",
        )
    )


def _uses_unsupported_entity_collection(
    test_case: TestCase,
    linked_requirements: list[AtomicRequirement],
    linked_obligations: list[TestObligation],
    source_package: SourcePackage | None,
) -> bool:
    support_text = _linked_support_text(linked_requirements, linked_obligations, source_package)
    supported_specs = _supported_entity_specs(linked_requirements, linked_obligations, support_text)
    for requested_entity in _requested_entities_from_bot_turns(test_case):
        if not _entity_supported_for_collection(requested_entity, supported_specs, support_text):
            return True
    return False


def _requested_entities_from_bot_turns(test_case: TestCase) -> list[str]:
    entities: list[str] = []
    for turn in test_case.turns:
        if turn.speaker.value != "bot" or _turn_mentions_agent_handoff(turn.text):
            continue
        for entity in _entity_collection_targets(turn.text):
            if entity and entity not in entities:
                entities.append(entity)
    return entities


def _entity_collection_targets(text: str) -> list[str]:
    targets: list[str] = []
    cue_pattern = "|".join(re.escape(cue) for cue in sorted(ENTITY_COLLECTION_CUES, key=len, reverse=True))
    pattern = re.compile(
        rf"\b(?:{cue_pattern})(?:\s+me)?(?:\s+for)?\s+(?:your|the|a|an)?\s*"
        r"([A-Za-z0-9][A-Za-z0-9' -]{1,80}?)"
        r"(?:[.?!,:;]|$|\s+so\b|\s+to\b|\s+before\b|\s+after\b|\s+when\b|\s+and\b)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        target = _normalize_entity_phrase(match.group(1))
        if target:
            targets.append(target)
    return targets


def _turn_mentions_agent_handoff(text: str) -> bool:
    normalized = _semantic_text_key(text)
    return any(cue in normalized for cue in ("agent", "human", "handoff", "transfer", "representative"))


def _entity_supported_for_collection(
    entity: str,
    supported_specs: list[EntitySpec],
    support_text: str,
) -> bool:
    for spec in supported_specs:
        if _entity_names_match(entity, spec.aliases):
            return True
    return _entity_supported_by_text(entity, support_text)


def _entity_supported_by_text(entity: str, support_text: str) -> bool:
    aliases = _entity_aliases(entity)
    for sentence in _sentences(support_text):
        normalized = _semantic_text_key(sentence)
        if not _contains_any_alias(normalized, aliases):
            continue
        if (
            any(cue in normalized for cue in CHATBOT_COLLECTION_SUPPORT_CUES)
            and any(cue in normalized for cue in ENTITY_COLLECTION_CUES)
        ):
            return True
    return False


def _has_unresolved_executable_placeholder(test_case: TestCase) -> bool:
    for _label, text in _executable_text_items(test_case):
        if _contains_placeholder(text):
            return True
    return False


def _required_entity_specs(
    linked_requirements: list[AtomicRequirement],
    linked_obligations: list[TestObligation],
    source_package: SourcePackage | None,
) -> list[EntitySpec]:
    if not any(_normalized_obligation_type(obligation) in ENTITY_DATA_OBLIGATION_TYPES for obligation in linked_obligations):
        return []
    support_text = _linked_support_text(linked_requirements, linked_obligations, source_package)
    specs = _entity_specs_from_metadata(linked_requirements, linked_obligations, require_required_keys=True)
    return [_with_entity_format(spec, support_text, linked_requirements, linked_obligations) for spec in specs]


def _supported_entity_specs(
    linked_requirements: list[AtomicRequirement],
    linked_obligations: list[TestObligation],
    support_text: str,
) -> list[EntitySpec]:
    specs = _entity_specs_from_metadata(linked_requirements, linked_obligations, require_required_keys=False)
    specs.extend(_entity_specs_from_support_text(support_text))
    unique: dict[str, EntitySpec] = {}
    for spec in specs:
        unique.setdefault(_semantic_text_key(spec.name), spec)
    return list(unique.values())


def _entity_specs_from_metadata(
    linked_requirements: list[AtomicRequirement],
    linked_obligations: list[TestObligation],
    *,
    require_required_keys: bool,
) -> list[EntitySpec]:
    specs: list[EntitySpec] = []
    for metadata in [
        *(requirement.metadata for requirement in linked_requirements),
        *(obligation.metadata for obligation in linked_obligations),
    ]:
        if not isinstance(metadata, Mapping):
            continue
        specs.extend(_entity_specs_from_metadata_mapping(metadata, require_required_keys=require_required_keys))
    return specs


def _entity_specs_from_metadata_mapping(
    metadata: Mapping[str, Any],
    *,
    require_required_keys: bool,
) -> list[EntitySpec]:
    specs: list[EntitySpec] = []
    for key, value in metadata.items():
        normalized_key = _semantic_text_key(str(key)).replace(" ", "_")
        if normalized_key not in ENTITY_METADATA_KEYS:
            continue
        if require_required_keys and not normalized_key.startswith("required_"):
            continue
        for name, format_text in _entity_names_from_metadata_value(value):
            spec = EntitySpec(name=name, aliases=tuple(_entity_aliases(name)), format_text=format_text)
            if spec.name:
                specs.append(spec)
    return specs


def _entity_names_from_metadata_value(value: Any) -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(_normalize_entity_phrase(value), "")]
    if isinstance(value, list):
        names: list[tuple[str, str]] = []
        for item in value:
            names.extend(_entity_names_from_metadata_value(item))
        return names
    if isinstance(value, dict):
        name_value = value.get("name") or value.get("entity") or value.get("id")
        format_text = " ".join(
            str(item)
            for key, item in value.items()
            if _semantic_text_key(str(key)).replace(" ", "_") in ENTITY_FORMAT_METADATA_KEYS
        )
        if name_value is not None:
            return [(_normalize_entity_phrase(str(name_value)), format_text)]
    return []


def _entity_specs_from_support_text(support_text: str) -> list[EntitySpec]:
    specs: list[EntitySpec] = []
    pattern = re.compile(
        r"\b(?:asks?|collects?|accepts?|requires?|provide|enter|share|give|type|input)\b"
        r"(?:\s+for)?\s+(?:your|the|a|an)?\s*"
        r"([A-Za-z0-9][A-Za-z0-9' -]{1,80}?)"
        r"(?:[.?!,:;]|$|\s+so\b|\s+to\b|\s+before\b|\s+after\b|\s+when\b|\s+and\b)",
        re.IGNORECASE,
    )
    for sentence in _sentences(support_text):
        normalized = _semantic_text_key(sentence)
        if not any(cue in normalized for cue in CHATBOT_COLLECTION_SUPPORT_CUES):
            continue
        for match in pattern.finditer(sentence):
            name = _normalize_entity_phrase(match.group(1))
            if name:
                specs.append(EntitySpec(name=name, aliases=tuple(_entity_aliases(name))))
    return specs


def _with_entity_format(
    spec: EntitySpec,
    support_text: str,
    linked_requirements: list[AtomicRequirement],
    linked_obligations: list[TestObligation],
) -> EntitySpec:
    format_parts = [spec.format_text]
    format_parts.extend(_metadata_format_strings(linked_requirements, linked_obligations))
    for sentence in _sentences(support_text):
        if _contains_any_alias(_semantic_text_key(sentence), spec.aliases):
            format_parts.append(sentence)
    return EntitySpec(
        name=spec.name,
        aliases=spec.aliases,
        format_text=" ".join(part for part in format_parts if part),
    )


def _metadata_format_strings(
    linked_requirements: list[AtomicRequirement],
    linked_obligations: list[TestObligation],
) -> list[str]:
    values: list[str] = []
    for metadata in [
        *(requirement.metadata for requirement in linked_requirements),
        *(obligation.metadata for obligation in linked_obligations),
    ]:
        if not isinstance(metadata, Mapping):
            continue
        for key, value in metadata.items():
            if _semantic_text_key(str(key)).replace(" ", "_") in ENTITY_FORMAT_METADATA_KEYS:
                values.extend(_metadata_strings(value))
    return values


def _has_valid_required_entity_data(test_case: TestCase, entity_specs: list[EntitySpec]) -> bool:
    for spec in entity_specs:
        candidates = _entity_value_candidates(test_case, spec)
        if not candidates or not any(_is_valid_entity_candidate(candidate, spec) for candidate in candidates):
            return False
    return True


def _entity_value_candidates(test_case: TestCase, spec: EntitySpec) -> list[str]:
    texts: list[str] = []
    for turn in test_case.turns:
        if turn.speaker.value in {"user", "system"}:
            texts.append(turn.text)
    if test_case.metadata is not None:
        texts.extend(_metadata_strings(test_case.metadata))
    texts.extend(_responses_after_entity_prompt(test_case, spec))

    candidates: list[str] = []
    for text in texts:
        candidates.extend(_value_candidates_from_text(text, spec))
    return [candidate for candidate in candidates if candidate]


def _responses_after_entity_prompt(test_case: TestCase, spec: EntitySpec) -> list[str]:
    responses: list[str] = []
    turns = test_case.turns
    for index, turn in enumerate(turns[:-1]):
        if turn.speaker.value != "bot":
            continue
        normalized = _semantic_text_key(turn.text)
        if not _contains_any_alias(normalized, spec.aliases):
            continue
        if not any(cue in normalized for cue in ENTITY_COLLECTION_CUES):
            continue
        next_turn = turns[index + 1]
        if next_turn.speaker.value == "user":
            responses.append(next_turn.text)
    return responses


def _value_candidates_from_text(text: str, spec: EntitySpec) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"(?<![A-Za-z0-9])\+?\d[\d .()-]{3,}\d(?![A-Za-z0-9])", text):
        candidates.append(match.group(0).strip())
    for match in re.finditer(r"(?<![A-Za-z0-9])[A-Z]{2,}[-_][A-Z0-9][A-Z0-9-_]{1,}(?![A-Za-z0-9])", text):
        candidates.append(match.group(0).strip())

    normalized = _semantic_text_key(text)
    if _contains_any_alias(normalized, spec.aliases):
        for alias in spec.aliases:
            if not alias or alias not in normalized:
                continue
            pattern = re.compile(
                rf"{re.escape(alias)}\s*(?:is|as|:|=|using|used)?\s+([^,.;!?]+)",
                re.IGNORECASE,
            )
            for match in pattern.finditer(normalized):
                candidates.append(match.group(1).strip())
    if not candidates and _looks_like_direct_entity_response(text):
        candidates.append(text.strip())
    return candidates


def _looks_like_direct_entity_response(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 80 or _contains_placeholder(stripped):
        return False
    normalized = _semantic_text_key(stripped)
    if len(normalized.split()) > 5:
        return False
    return bool(re.search(r"[A-Za-z0-9]", stripped))


def _is_valid_entity_candidate(value: str, spec: EntitySpec) -> bool:
    stripped = value.strip()
    if not stripped or _contains_placeholder(stripped):
        return False
    digits = re.sub(r"\D", "", stripped)
    digit_lengths = _digit_lengths_from_format(spec.format_text)
    if digit_lengths:
        return len(digits) in digit_lengths and _digits_are_not_obviously_invalid(digits)
    if _format_requires_numeric(spec.format_text) and not digits:
        return False
    if _entity_name_implies_number(spec) and not digits:
        return False
    if digits and not _digits_are_not_obviously_invalid(digits):
        return False
    return True


def _digit_lengths_from_format(format_text: str) -> set[int]:
    normalized = _semantic_text_key(format_text)
    lengths: set[int] = set()
    for match in re.finditer(r"\b(?:exactly\s+)?(\d{1,3})\s+digits?\b", normalized):
        lengths.add(int(match.group(1)))
    return lengths


def _format_requires_numeric(format_text: str) -> bool:
    normalized = _semantic_text_key(format_text)
    return any(cue in normalized for cue in ("digits only", "numbers only", "numeric only", "numeric value"))


def _entity_name_implies_number(spec: EntitySpec) -> bool:
    return any("number" in alias for alias in spec.aliases)


def _digits_are_not_obviously_invalid(digits: str) -> bool:
    return bool(digits) and len(set(digits)) > 1


def _requires_api_setup(linked_obligations: list[TestObligation]) -> bool:
    for obligation in linked_obligations:
        obligation_type = _normalized_obligation_type(obligation)
        if obligation_type in API_SETUP_OBLIGATION_TYPES:
            return True
        text = _semantic_text_key(
            " ".join(
                item
                for item in [
                    obligation.obligation_type,
                    obligation.description or "",
                    obligation.coverage_intent or "",
                    _metadata_to_strings(obligation.metadata),
                ]
                if item
            )
        )
        if "api" in text and any(cue in text for cue in ("success", "error", "backend", "stub")):
            return True
    return False


def _has_api_setup_or_stub_data(test_case: TestCase) -> bool:
    setup_text = " ".join(
        [
            *(turn.text for turn in test_case.turns if turn.speaker.value == "system"),
            *(_metadata_strings(test_case.metadata) if test_case.metadata else []),
        ]
    )
    normalized = _semantic_text_key(setup_text)
    if not normalized:
        return False
    return any(
        cue in normalized
        for cue in (
            "setup",
            "precondition",
            "test data",
            "stub",
            "api returns",
            "api response",
            "success payload",
            "error payload",
            "backend",
            "registered",
            "no active",
            "200 ok",
            "400",
            "401",
            "404",
            "429",
            "500",
        )
    )


def _has_unsupported_exact_wording_claim(
    test_case: TestCase,
    linked_requirements: list[AtomicRequirement],
    linked_obligations: list[TestObligation],
    source_package: SourcePackage,
) -> bool:
    source_text = _linked_source_text(linked_requirements, linked_obligations, source_package)
    if not source_text.strip():
        return False
    normalized_source = _semantic_text_key(source_text)
    for assertion in test_case.assertions:
        phrase = _exact_wording_phrase(assertion)
        if phrase and _semantic_text_key(phrase) not in normalized_source:
            return True
    return False


def _exact_wording_phrase(assertion) -> str | None:
    assertion_type = _semantic_text_key(assertion.assertion_type)
    target = _semantic_text_key(assertion.target)
    expected = _text_value(assertion.expected).strip()
    expected_key = _semantic_text_key(expected)
    has_exact_type = any(cue in assertion_type for cue in ("exact", "equals", "contains text", "required message"))
    has_exact_target = any(cue in target for cue in ("text", "message"))
    has_exact_expected = any(cue in expected_key for cue in ("state exactly", "say exactly", "respond exactly"))
    if not (has_exact_type or has_exact_expected or (has_exact_target and "contains text" in assertion_type)):
        return None
    quoted = re.findall(r'"([^"]+)"', expected)
    if quoted:
        return max(quoted, key=len)
    return expected


def _is_weak_or_meta_assertion(assertion) -> bool:
    combined = _semantic_text_key(
        " ".join(
            [
                assertion.assertion_type,
                assertion.target,
                _text_value(assertion.expected),
                _metadata_to_strings(assertion.metadata),
            ]
        )
    )
    weak_phrases = (
        "responds appropriately",
        "handles the request",
        "behaves correctly",
        "meets the requirement",
        "is covered",
        "traceability is maintained",
        "coverage is maintained",
    )
    if any(phrase in combined for phrase in weak_phrases):
        return True
    meta_cues = ("traceability", "source refs", "source ref", "requirement id", "obligation id", "test case links")
    if not any(cue in combined for cue in meta_cues):
        return False
    return not _has_observable_assertion_criteria(combined)


def _has_observable_assertion_criteria(text: str) -> bool:
    return any(
        cue in text
        for cue in (
            "bot response",
            "chatbot response",
            "bot must",
            "chatbot must",
            "asks",
            "says",
            "states",
            "displays",
            "transfers",
            "must not",
            "does not",
        )
    )


def _metadata_or_existing_reasons_flag_review(test_case: TestCase) -> bool:
    texts = []
    if test_case.rejection_reasons is not None:
        texts.extend(test_case.rejection_reasons)
    if test_case.metadata is not None:
        texts.extend(_metadata_strings(test_case.metadata))
    for assertion in test_case.assertions:
        if assertion.metadata is not None:
            texts.extend(_metadata_strings(assertion.metadata))
    combined = _semantic_text_key(" ".join(texts))
    return any(
        cue in combined
        for cue in (
            "unsupported",
            "non executable",
            "nonexecutable",
            "needs review",
            "needsreview",
            "uncertain",
            "uncertainty",
        )
    )


def _linked_source_text(
    linked_requirements: list[AtomicRequirement],
    linked_obligations: list[TestObligation],
    source_package: SourcePackage,
) -> str:
    source_refs = [
        *(source_ref for requirement in linked_requirements for source_ref in (requirement.source_refs or [])),
        *(source_ref for obligation in linked_obligations for source_ref in obligation.source_refs),
    ]
    chunks_by_ref = {
        (chunk.document_id, chunk.chunk_id): chunk.text
        for chunk in source_package.chunks
    }
    text_parts: list[str] = []
    seen: set[tuple[str, str | None]] = set()
    for source_ref in source_refs:
        key = (source_ref.document_id, source_ref.chunk_id)
        if key in seen:
            continue
        if source_ref.quote:
            text_parts.append(source_ref.quote)
        if source_ref.chunk_id is not None:
            chunk_text = chunks_by_ref.get((source_ref.document_id, source_ref.chunk_id))
            if chunk_text:
                text_parts.append(chunk_text)
        seen.add(key)
    return " ".join(text_parts)


def _linked_support_text(
    linked_requirements: list[AtomicRequirement],
    linked_obligations: list[TestObligation],
    source_package: SourcePackage | None,
) -> str:
    parts = [
        *(requirement.statement for requirement in linked_requirements),
        *(obligation.description or "" for obligation in linked_obligations),
        *(obligation.coverage_intent or "" for obligation in linked_obligations),
        *(_metadata_to_strings(requirement.metadata) for requirement in linked_requirements),
        *(_metadata_to_strings(obligation.metadata) for obligation in linked_obligations),
    ]
    if source_package is not None:
        parts.append(_linked_source_text(linked_requirements, linked_obligations, source_package))
    return " ".join(part for part in parts if part)


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.?!])\s+|\n+", text) if part.strip()]


def _normalize_entity_phrase(text: str) -> str:
    normalized = _semantic_text_key(text)
    words = normalized.split()
    while words and words[0] in {"your", "the", "a", "an"}:
        words.pop(0)
    return " ".join(words)


def _entity_aliases(name: str) -> list[str]:
    normalized = _normalize_entity_phrase(name)
    aliases = {normalized}
    if normalized:
        aliases.add(normalized.replace(" ", ""))
    words = normalized.split()
    if words[-1:] == ["number"] and len(words) > 1:
        base = " ".join(words[:-1])
        aliases.add(base)
        aliases.add(base.replace(" ", ""))
    return [alias for alias in aliases if alias]


def _contains_any_alias(text: str, aliases: Iterable[str]) -> bool:
    normalized = _semantic_text_key(text)
    compact = normalized.replace(" ", "")
    for alias in aliases:
        alias_key = _semantic_text_key(alias)
        if not alias_key:
            continue
        if alias_key in normalized or alias_key.replace(" ", "") in compact:
            return True
    return False


def _entity_names_match(entity: str, aliases: Iterable[str]) -> bool:
    entity_aliases = _entity_aliases(entity)
    for alias in aliases:
        if _contains_any_alias(entity, [alias]):
            return True
        if any(_contains_any_alias(alias, [entity_alias]) for entity_alias in entity_aliases):
            return True
    return False


def _contains_placeholder(text: str) -> bool:
    placeholder_patterns = (
        re.compile(r"<[^>\n]+>"),
        re.compile(r"\{\{[^}\n]+\}\}"),
        re.compile(r"\[[A-Z][A-Z0-9_ -]{1,}\]"),
        re.compile(r"\b(TBD|TODO|INSERT|sample value here)\b", re.IGNORECASE),
    )
    return any(pattern.search(text) for pattern in placeholder_patterns)


def _executable_text_items(test_case: TestCase) -> list[tuple[str, str]]:
    items = [(f"turn.{turn.turn_id}", turn.text) for turn in test_case.turns]
    for assertion in test_case.assertions:
        items.append((f"assertion.{assertion.assertion_id}.target", assertion.target))
        items.append((f"assertion.{assertion.assertion_id}.expected", _text_value(assertion.expected)))
    if test_case.metadata is not None:
        items.extend(("metadata", value) for value in _metadata_strings(test_case.metadata))
    return items


def _metadata_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, bool):
        return [str(value)]
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_metadata_strings(item))
        return strings
    if isinstance(value, dict):
        strings = []
        for key, item in value.items():
            strings.append(str(key))
            strings.extend(_metadata_strings(item))
        return strings
    return [str(value)]


def _metadata_to_strings(value: Any) -> str:
    return " ".join(_metadata_strings(value))


def _text_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _normalized_obligation_type(obligation: TestObligation) -> str:
    return "_".join(obligation.obligation_type.lower().replace("-", "_").split())


def _semantic_text_key(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", lowered)
    lowered = lowered.replace("10-digit", "10 digit")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(lowered.split())


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _validation_summary(test_cases: list[TestCase]) -> dict[str, int]:
    return {
        "valid": sum(1 for test_case in test_cases if test_case.status == TestCaseStatus.VALID),
        "needs_review": sum(1 for test_case in test_cases if test_case.status == TestCaseStatus.NEEDS_REVIEW),
        "rejected": sum(1 for test_case in test_cases if test_case.status == TestCaseStatus.REJECTED),
        "export_eligible": sum(1 for test_case in test_cases if test_case.is_exportable),
    }


def _load_draft_suite(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
) -> DraftTestSuite:
    try:
        return store.load_model(
            DraftTestSuite,
            project_id,
            run_id,
            DRAFT_TESTS_STAGE,
            DRAFT_TEST_SUITE_ARTIFACT_NAME,
        )
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise DraftTestSuiteArtifactError(f"Failed to load DraftTestSuite artifact: {exc}") from exc


def _load_governed_ledger(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
) -> GovernedRequirementLedger:
    try:
        return store.load_model(
            GovernedRequirementLedger,
            project_id,
            run_id,
            GOVERNED_REQUIREMENTS_STAGE,
            GOVERNED_REQUIREMENT_LEDGER_ARTIFACT_NAME,
        )
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise InvalidTestValidationInputError(f"Failed to load GovernedRequirementLedger artifact: {exc}") from exc


def _load_obligation_ledger(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
) -> TestObligationLedger:
    try:
        return store.load_model(
            TestObligationLedger,
            project_id,
            run_id,
            TEST_OBLIGATIONS_STAGE,
            TEST_OBLIGATION_LEDGER_ARTIFACT_NAME,
        )
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise InvalidTestValidationInputError(f"Failed to load TestObligationLedger artifact: {exc}") from exc


def _load_source_package_if_present(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
) -> SourcePackage | None:
    if not store.exists(project_id, run_id, SOURCE_PACKAGE_STAGE, SOURCE_PACKAGE_ARTIFACT_NAME):
        return None
    try:
        return store.load_model(
            SourcePackage,
            project_id,
            run_id,
            SOURCE_PACKAGE_STAGE,
            SOURCE_PACKAGE_ARTIFACT_NAME,
        )
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise InvalidTestValidationInputError(f"Failed to load SourcePackage artifact: {exc}") from exc


def _write_validated_suite(
    store: ArtifactStore,
    *,
    run_id: str,
    suite: ValidatedTestSuite,
):
    try:
        return store.write_json(
            suite.project_id,
            run_id,
            VALIDATED_TESTS_STAGE,
            VALIDATED_TEST_SUITE_ARTIFACT_NAME,
            suite,
        )
    except ArtifactStoreError as exc:
        raise TestValidationPersistenceError(f"Failed to save ValidatedTestSuite artifact: {exc}") from exc


def _write_coverage_report(
    store: ArtifactStore,
    *,
    run_id: str,
    report: CoverageReport,
):
    try:
        return store.write_json(
            report.project_id,
            run_id,
            VALIDATED_TESTS_STAGE,
            COVERAGE_REPORT_ARTIFACT_NAME,
            report,
        )
    except ArtifactStoreError as exc:
        raise TestValidationPersistenceError(f"Failed to save CoverageReport artifact: {exc}") from exc


def _artifact_context_from_draft_suite_path(path: Path) -> tuple[Path, str, str]:
    if path.name != "draft_test_suite.json":
        raise DraftTestSuiteArtifactError(
            f"DraftTestSuite artifact must be named draft_test_suite.json: {path}"
        )
    if path.parent.name != DRAFT_TESTS_STAGE:
        raise DraftTestSuiteArtifactError(
            f"DraftTestSuite artifact must be under {DRAFT_TESTS_STAGE}: {path}"
        )
    run_dir = path.parent.parent
    project_dir = run_dir.parent
    return project_dir.parent, project_dir.name, run_dir.name
