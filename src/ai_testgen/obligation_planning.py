from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_testgen.artifact_store import ArtifactStore, ArtifactStoreError
from ai_testgen.project_config import PROJECT_CONFIG_ARTIFACT_NAME, PROJECT_CONFIG_STAGE
from ai_testgen.requirement_governance import (
    GOVERNED_REQUIREMENT_LEDGER_ARTIFACT_NAME,
    GOVERNED_REQUIREMENTS_STAGE,
)
from ai_testgen.schemas import (
    AtomicRequirement,
    AtomicRequirementStatus,
    GovernedRequirementLedger,
    ProjectConfig,
    SchemaValidationError,
    TestObligationLedger,
)
from ai_testgen.validators import validate_obligation_links


TEST_OBLIGATIONS_STAGE = "06_test_obligations"
TEST_OBLIGATION_LEDGER_ARTIFACT_NAME = "test_obligation_ledger"
OBLIGATION_LEDGER_ID = "obl_ledger_001"
CONFLICT_BLOCKED_REASON = "Conflicting requirement must be resolved before normal obligations can be planned."
POLICY_SKIPPED_REASON = "Coverage policy does not require obligations for this requirement."


class TestObligationPlanningError(Exception):
    """Base error for C10 test obligation planning failures."""


class GovernedLedgerArtifactError(TestObligationPlanningError):
    """Raised when the input GovernedRequirementLedger artifact cannot be used."""


class ProjectConfigArtifactError(TestObligationPlanningError):
    """Raised when the required ProjectConfig artifact cannot be used."""


class InvalidTestObligationLedgerError(TestObligationPlanningError):
    """Raised when planned obligations fail C10 validation."""


class TestObligationPlanningPersistenceError(TestObligationPlanningError):
    """Raised when C10 cannot persist its output artifact."""


@dataclass(frozen=True)
class TestObligationPlanningResult:
    obligation_ledger: TestObligationLedger
    obligation_ledger_path: Path


@dataclass(frozen=True)
class _CoverageSettings:
    require_positive: bool
    require_negative: bool
    require_boundary: bool


@dataclass(frozen=True)
class _ObligationPlan:
    obligation_type: str
    planning_rule: str
    description: str
    coverage_intent: str
    source_supported_negative: bool | None = None


def plan_obligations_from_governed_ledger_artifact(
    governed_ledger_path: str | Path,
) -> TestObligationPlanningResult:
    governed_path = Path(governed_ledger_path)
    artifact_root, project_id, run_id = _artifact_context_from_governed_ledger_path(governed_path)
    store = ArtifactStore(artifact_root)
    project_config = _load_project_config(store, project_id=project_id, run_id=run_id)
    governed_ledger = _load_governed_ledger(store, project_id=project_id, run_id=run_id)
    if governed_ledger.project_id != project_id:
        raise GovernedLedgerArtifactError(
            f"GovernedRequirementLedger artifact project directory must match project_id "
            f"{governed_ledger.project_id}: {governed_path}"
        )

    obligation_ledger = plan_test_obligations(governed_ledger, project_config)
    written = _write_obligation_ledger(store, run_id=run_id, obligation_ledger=obligation_ledger)
    return TestObligationPlanningResult(
        obligation_ledger=obligation_ledger,
        obligation_ledger_path=written.path,
    )


def plan_test_obligations(
    governed_ledger: GovernedRequirementLedger,
    project_config: ProjectConfig,
) -> TestObligationLedger:
    if governed_ledger.project_id != project_config.project_id:
        raise InvalidTestObligationLedgerError(
            "GovernedRequirementLedger project_id must match ProjectConfig project_id"
        )

    coverage_settings = _coverage_settings(project_config.coverage_policy)
    obligations: list[dict[str, Any]] = []
    next_obligation_number = 1
    for requirement in governed_ledger.requirements:
        if requirement.status == AtomicRequirementStatus.REJECTED:
            continue
        if requirement.status == AtomicRequirementStatus.CONFLICTING:
            obligations.append(
                _obligation_data(
                    requirement,
                    obligation_number=next_obligation_number,
                    obligation_type="blocked_conflict",
                    status="blocked_unclear_requirement",
                    blocked_reason=CONFLICT_BLOCKED_REASON,
                    metadata={
                        "chatbot_obligation": False,
                        "planning_rule": "conflicting_requirement",
                    },
                )
            )
            next_obligation_number += 1
            continue
        if not requirement.is_eligible_for_obligation_planning:
            continue

        if _is_api_schema_only_requirement(requirement):
            obligations.append(
                _obligation_data(
                    requirement,
                    obligation_number=next_obligation_number,
                    obligation_type="non_chatbot_api_schema",
                    status="skipped_by_policy",
                    blocked_reason="API-schema-only requirement is not a chatbot test obligation by default.",
                    description=(
                        "Do not send this API schema detail to chatbot test generation: "
                        f"{requirement.statement}"
                    ),
                    coverage_intent="Keep raw API response-shape coverage out of C11 chatbot test drafting.",
                    metadata={
                        "chatbot_obligation": False,
                        "planning_rule": "api_schema_only_requirement",
                    },
                )
            )
            next_obligation_number += 1
            continue

        obligation_plans = _obligation_plans_for_requirement(requirement, coverage_settings)
        if not obligation_plans:
            obligations.append(
                _obligation_data(
                    requirement,
                    obligation_number=next_obligation_number,
                    obligation_type="skipped_by_policy",
                    status="skipped_by_policy",
                    blocked_reason=POLICY_SKIPPED_REASON,
                    metadata={
                        "chatbot_obligation": False,
                        "planning_rule": "no_supported_chatbot_obligation",
                    },
                )
            )
            next_obligation_number += 1
            continue

        for obligation_plan in obligation_plans:
            obligations.append(
                _obligation_data(
                    requirement,
                    obligation_number=next_obligation_number,
                    obligation_type=obligation_plan.obligation_type,
                    status="planned",
                    description=obligation_plan.description,
                    coverage_intent=obligation_plan.coverage_intent,
                    metadata=_planned_obligation_metadata(obligation_plan),
                )
            )
            next_obligation_number += 1

    ledger_data = {
        "obligation_ledger_id": OBLIGATION_LEDGER_ID,
        "project_id": governed_ledger.project_id,
        "governed_ledger_id": governed_ledger.governed_ledger_id,
        "obligations": obligations,
        "coverage_policy_snapshot": project_config.coverage_policy,
    }

    try:
        obligation_ledger = TestObligationLedger.from_dict(ledger_data)
        validate_obligation_links(obligation_ledger.obligations, governed_ledger.requirements)
    except SchemaValidationError as exc:
        raise InvalidTestObligationLedgerError(f"Invalid TestObligationLedger data: {exc}") from exc

    return obligation_ledger


def _obligation_data(
    requirement: AtomicRequirement,
    *,
    obligation_number: int,
    obligation_type: str,
    status: str,
    blocked_reason: str | None = None,
    description: str | None = None,
    coverage_intent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = {
        "obligation_id": f"obl_{obligation_number:03d}",
        "requirement_id": requirement.requirement_id,
        "obligation_type": obligation_type,
        "status": status,
        "source_refs": [source_ref.to_dict() for source_ref in requirement.source_refs or []],
    }
    if blocked_reason is not None:
        data["blocked_reason"] = blocked_reason
    if description is not None:
        data["description"] = description
    if coverage_intent is not None:
        data["coverage_intent"] = coverage_intent
    if metadata is not None:
        data["metadata"] = metadata
    return data


def _obligation_plans_for_requirement(
    requirement: AtomicRequirement,
    coverage_settings: _CoverageSettings,
) -> list[_ObligationPlan]:
    if not (
        coverage_settings.require_positive
        or coverage_settings.require_negative
        or coverage_settings.require_boundary
    ):
        return []

    requirement_type = _normalized_requirement_type(requirement)
    plans: list[_ObligationPlan] = []
    if _plans_entity_collection(requirement):
        entity_planning_rule = "entity_collection" if requirement_type == "entity_collection" else requirement_type
        if coverage_settings.require_negative:
            plans.append(_missing_entity_plan(requirement, entity_planning_rule))
        if coverage_settings.require_positive:
            plans.append(_provided_entity_plan(requirement, entity_planning_rule))
        if coverage_settings.require_negative and _supports_invalid_entity(requirement):
            plans.append(_invalid_entity_plan(requirement, "entity_collection_validation"))
        return _dedupe_plans(plans)

    if requirement_type == "faq_answer":
        if coverage_settings.require_positive:
            plans.extend(
                [
                    _direct_faq_answer_plan(requirement, "faq_answer_direct"),
                    _paraphrase_faq_answer_plan(requirement, "faq_answer_paraphrase"),
                ]
            )
        if coverage_settings.require_negative and _supports_adjacent_topic_refusal(requirement):
            plans.append(_fallback_plan(requirement, "faq_adjacent_topic_refusal"))
        return _dedupe_plans(plans)

    if _is_user_facing_api_error_requirement(requirement):
        if coverage_settings.require_negative:
            plans.append(_api_error_plan(requirement, requirement_type))
        return plans

    if _is_user_facing_api_success_requirement(requirement):
        if coverage_settings.require_positive:
            plans.append(_api_success_plan(requirement, requirement_type))
        return plans

    if _is_input_validation_requirement(requirement):
        if coverage_settings.require_negative:
            plans.append(_invalid_entity_plan(requirement, requirement_type))
        return plans

    if _is_missing_entity_requirement(requirement):
        if coverage_settings.require_negative:
            plans.append(_missing_entity_plan(requirement, requirement_type))
        return plans

    if _is_provided_entity_requirement(requirement):
        if coverage_settings.require_positive:
            plans.append(_provided_entity_plan(requirement, requirement_type))
        return plans

    if _is_human_handoff_requirement(requirement):
        if coverage_settings.require_positive or coverage_settings.require_negative:
            plans.append(_human_handoff_plan(requirement, requirement_type))
        return plans

    if requirement_type in {"intent_handling", "global_intent_handling", "conversation_routing"}:
        if coverage_settings.require_positive:
            plans.append(_global_intent_plan(requirement, requirement_type))
        return plans

    if requirement_type == "fallback_handling":
        if coverage_settings.require_negative:
            plans.append(_fallback_plan(requirement, requirement_type))
        return plans

    if _is_faq_like_requirement(requirement):
        if coverage_settings.require_positive:
            plans.append(_direct_faq_answer_plan(requirement, requirement_type))
        return plans

    if requirement_type == "api_integration":
        if coverage_settings.require_positive:
            plans.append(_api_success_plan(requirement, requirement_type))
        return plans

    if requirement_type == "business_rule" and _metadata_present(requirement, "threshold"):
        if coverage_settings.require_boundary:
            plans.append(_boundary_plan(requirement, requirement_type))
        return plans

    return []


def _coverage_settings(coverage_policy: dict[str, Any]) -> _CoverageSettings:
    return _CoverageSettings(
        require_positive=_coverage_flag(coverage_policy, "require_positive_tests", default=True),
        require_negative=_coverage_flag(coverage_policy, "require_negative_tests", default=False),
        require_boundary=_coverage_flag(coverage_policy, "require_boundary_tests", default=False),
    )


def _planned_obligation_metadata(obligation_plan: _ObligationPlan) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "chatbot_obligation": True,
        "planning_rule": obligation_plan.planning_rule,
    }
    if obligation_plan.source_supported_negative is not None:
        metadata["source_supported_negative"] = obligation_plan.source_supported_negative
    return metadata


def _missing_entity_plan(requirement: AtomicRequirement, planning_rule: str) -> _ObligationPlan:
    rule = (
        "entity_collection_missing_entity"
        if planning_rule == "entity_collection"
        else "missing_entity_requirement"
    )
    return _ObligationPlan(
        obligation_type="missing_entity",
        planning_rule=rule,
        description=(
            "Verify the chatbot asks for the required entity before continuing: "
            f"{requirement.statement}"
        ),
        coverage_intent="Exercise the documented missing-entity branch without inventing a generic negative case.",
        source_supported_negative=True,
    )


def _provided_entity_plan(requirement: AtomicRequirement, planning_rule: str) -> _ObligationPlan:
    return _ObligationPlan(
        obligation_type="provided_entity",
        planning_rule=f"{planning_rule}_provided_entity",
        description=(
            "Verify the chatbot proceeds when the required entity is provided: "
            f"{requirement.statement}"
        ),
        coverage_intent="Exercise the documented provided-entity path for the chatbot flow.",
    )


def _invalid_entity_plan(requirement: AtomicRequirement, planning_rule: str) -> _ObligationPlan:
    return _ObligationPlan(
        obligation_type="invalid_entity",
        planning_rule=f"{planning_rule}_invalid_entity",
        description=(
            "Verify the chatbot handles the documented invalid entity condition: "
            f"{requirement.statement}"
        ),
        coverage_intent="Exercise a source-backed invalid-input condition only.",
        source_supported_negative=True,
    )


def _api_success_plan(requirement: AtomicRequirement, planning_rule: str) -> _ObligationPlan:
    return _ObligationPlan(
        obligation_type="api_success",
        planning_rule=f"{planning_rule}_api_success",
        description=(
            "Verify the chatbot behavior for the documented API-backed success path: "
            f"{requirement.statement}"
        ),
        coverage_intent="Exercise only user-facing success behavior, not raw API response shape.",
    )


def _api_error_plan(requirement: AtomicRequirement, planning_rule: str) -> _ObligationPlan:
    return _ObligationPlan(
        obligation_type="api_error",
        planning_rule=f"{planning_rule}_api_error",
        description=(
            "Verify the chatbot behavior for the documented API error condition: "
            f"{requirement.statement}"
        ),
        coverage_intent="Exercise only documented user-facing API error behavior.",
        source_supported_negative=True,
    )


def _fallback_plan(requirement: AtomicRequirement, planning_rule: str) -> _ObligationPlan:
    return _ObligationPlan(
        obligation_type="fallback",
        planning_rule=f"{planning_rule}_fallback",
        description=(
            "Verify the chatbot uses the documented fallback behavior: "
            f"{requirement.statement}"
        ),
        coverage_intent="Exercise a source-backed fallback branch, not a generic negative case.",
        source_supported_negative=True,
    )


def _human_handoff_plan(requirement: AtomicRequirement, planning_rule: str) -> _ObligationPlan:
    return _ObligationPlan(
        obligation_type="human_handoff",
        planning_rule=f"{planning_rule}_human_handoff",
        description=(
            "Verify the chatbot performs the documented handoff behavior: "
            f"{requirement.statement}"
        ),
        coverage_intent="Exercise a documented transfer-to-human path.",
    )


def _direct_faq_answer_plan(requirement: AtomicRequirement, planning_rule: str) -> _ObligationPlan:
    return _ObligationPlan(
        obligation_type="direct_faq_answer",
        planning_rule=f"{planning_rule}_direct_faq_answer",
        description=(
            "Verify the chatbot answers the documented FAQ directly: "
            f"{requirement.statement}"
        ),
        coverage_intent="Exercise the direct documented FAQ answer.",
    )


def _paraphrase_faq_answer_plan(requirement: AtomicRequirement, planning_rule: str) -> _ObligationPlan:
    return _ObligationPlan(
        obligation_type="paraphrase_faq_answer",
        planning_rule=f"{planning_rule}_paraphrase_faq_answer",
        description=(
            "Verify the chatbot answers a paraphrased version of the documented FAQ: "
            f"{requirement.statement}"
        ),
        coverage_intent="Exercise a semantically equivalent paraphrase of the documented FAQ.",
    )


def _global_intent_plan(requirement: AtomicRequirement, planning_rule: str) -> _ObligationPlan:
    return _ObligationPlan(
        obligation_type="global_intent",
        planning_rule=f"{planning_rule}_global_intent",
        description=(
            "Verify the chatbot follows the documented intent branch: "
            f"{requirement.statement}"
        ),
        coverage_intent="Exercise a named source-backed intent path.",
    )


def _boundary_plan(requirement: AtomicRequirement, planning_rule: str) -> _ObligationPlan:
    return _ObligationPlan(
        obligation_type="boundary",
        planning_rule=f"{planning_rule}_boundary",
        description=(
            "Verify the documented boundary condition: "
            f"{requirement.statement}"
        ),
        coverage_intent="Exercise a source-backed boundary condition.",
    )


def _dedupe_plans(plans: list[_ObligationPlan]) -> list[_ObligationPlan]:
    deduped: list[_ObligationPlan] = []
    seen: set[str] = set()
    for plan in plans:
        if plan.obligation_type not in seen:
            deduped.append(plan)
            seen.add(plan.obligation_type)
    return deduped


def _coverage_flag(coverage_policy: dict[str, Any], key: str, *, default: bool) -> bool:
    value = coverage_policy.get(key, default)
    if type(value) is not bool:
        raise InvalidTestObligationLedgerError(f"coverage_policy.{key} must be a boolean")
    return value


def _normalized_requirement_type(requirement: AtomicRequirement) -> str:
    return "_".join(requirement.requirement_type.lower().replace("-", "_").split())


def _normalized_statement(requirement: AtomicRequirement) -> str:
    return " ".join(requirement.statement.lower().split())


def _normalized_requirement_context(requirement: AtomicRequirement) -> str:
    text_parts = [requirement.statement]
    text_parts.extend(
        source_ref.quote
        for source_ref in requirement.source_refs or []
        if source_ref.quote
    )
    if requirement.metadata:
        text_parts.extend(_metadata_text_values(requirement.metadata))
    return " ".join(" ".join(part.lower().split()) for part in text_parts if part)


def _is_api_schema_only_requirement(requirement: AtomicRequirement) -> bool:
    if _metadata_truthy(requirement, "chatbot_testable") or _documents_user_facing_requirement(requirement):
        return False
    if _metadata_truthy(requirement, "api_schema_only") or _metadata_truthy(
        requirement,
        "non_chatbot_api_schema",
    ) or _metadata_value_in(
        requirement,
        "test_track",
        {"api_contract", "api_schema"},
    ) or _has_backend_contract_metadata(requirement):
        return True

    requirement_type = _normalized_requirement_type(requirement)
    context = _normalized_requirement_context(requirement)
    if requirement_type in {
        "response_contract",
        "request_contract",
        "response_field",
        "request_field",
        "functional_response_content",
        "input_type",
        "api_contract",
        "object_schema",
    }:
        return True
    if requirement_type in {
        "validation_rule",
        "conditional_validation_rule",
        "validation_constraint",
    } and _mentions_backend_contract_detail(context):
        return True
    if requirement_type in {"api_error_handling", "api_success_handling", "api_behavior"}:
        return True
    return False


def _documents_user_facing_requirement(requirement: AtomicRequirement) -> bool:
    return (
        _metadata_truthy(requirement, "documents_user_facing_bot_behavior")
        or _metadata_truthy(requirement, "user_facing")
        or _metadata_truthy(requirement, "bot_visible")
        or _metadata_truthy(requirement, "chatbot_testable")
        or _documents_user_facing_bot_behavior(_normalized_requirement_context(requirement))
    )


def _documents_user_facing_bot_behavior(text: str) -> bool:
    return any(
        cue in text
        for cue in (
            "bot must respond",
            "bot should respond",
            "chatbot must respond",
            "chatbot should respond",
            "assistant must respond",
            "assistant should respond",
            "standardized bot output",
            "standardized output",
            "bot output",
            "must prompt",
            "should prompt",
            "prompt the user",
            "must ask",
            "should ask",
            "bot must tell",
            "bot should tell",
            "chatbot must tell",
            "chatbot should tell",
            "tell the user",
            "show the user",
            "display to the user",
            "present to the user",
            "must transfer",
            "should transfer",
            "transfer the conversation",
            "connect you with an agent",
            "must end the conversation",
            "should end the conversation",
            "must say",
            "should say",
            "say that",
            "before responding",
            "in chat",
            "user-facing",
            "visible to the user",
        )
    )


def _mentions_backend_contract_detail(text: str) -> bool:
    return any(
        cue in text
        for cue in (
            "api response",
            "api request",
            "response body",
            "request body",
            "response schema",
            "request schema",
            "payload",
            "schema",
            "field",
            "property",
            "object",
            "parameter",
            "endpoint",
            "json",
            "top-level",
            "data object",
            "response includes",
            "request includes",
            "must be a string",
            "must be an integer",
            "must be a number",
            "must be a boolean",
            "url string",
            "maximum length",
            "max length",
            "nullable",
            "nullability",
            "enum:",
            "required field",
        )
    )


def _has_backend_contract_metadata(requirement: AtomicRequirement) -> bool:
    backend_keys = {
        "backendonly",
        "apischemaonly",
        "nonchatbotapischema",
        "apicontract",
        "responsefield",
        "requestfield",
        "objectschema",
        "fieldtype",
        "nullability",
        "maxlength",
        "required",
        "payloadschema",
        "responseschema",
        "request" + "schema",
        "endpoint",
    }
    return any(_metadata_has_key(requirement, key) for key in backend_keys)


def _is_user_facing_api_error_requirement(requirement: AtomicRequirement) -> bool:
    requirement_type = _normalized_requirement_type(requirement)
    if requirement_type not in {
        "api_error_handling",
        "error_response_mapping",
        "response_behavior",
    } and not _metadata_present_any(requirement, {"documented_errors", "error_condition"}):
        return False
    return _is_documented_error_condition(requirement) and _documents_user_facing_requirement(requirement)


def _is_documented_error_condition(requirement: AtomicRequirement) -> bool:
    if _metadata_present_any(
        requirement,
        {
            "documented_errors",
            "error_condition",
            "fallback",
            "human_handoff",
            "unsupported_self_service",
            "no_result_condition",
        },
    ):
        return True
    return _mentions_api_error_condition(_normalized_requirement_context(requirement))


def _mentions_api_error_condition(text: str) -> bool:
    return any(
        cue in text
        for cue in (
            "api returns",
            "api error",
            "http 400",
            "http 401",
            "http 403",
            "http 404",
            "http 429",
            "http 500",
            "error code",
            "err_",
            "incorrect format",
            "server rejects",
            "not found",
            "no matching",
            "no result",
            "no results",
            "rate limit",
            "unauthorized",
            "unavailable",
            "timeout",
            "database failure",
            "upstream service failure",
            "service failure",
        )
    )


def _is_user_facing_api_success_requirement(requirement: AtomicRequirement) -> bool:
    requirement_type = _normalized_requirement_type(requirement)
    if requirement_type == "status_response":
        return _documents_user_facing_requirement(requirement)
    if requirement_type in {"api_behavior", "api_success_handling", "response_behavior"}:
        return _documents_user_facing_requirement(requirement)
    if requirement_type in {"response_field", "functional_response_content"}:
        return _documents_user_facing_requirement(requirement)
    return False


def _is_input_validation_requirement(requirement: AtomicRequirement) -> bool:
    requirement_type = _normalized_requirement_type(requirement)
    if requirement_type in {"input_validation", "validation_constraint"}:
        return _supports_invalid_entity(requirement)
    return False


def _supports_invalid_entity(requirement: AtomicRequirement) -> bool:
    if _metadata_present_any(
        requirement,
        {
            "validation_rules",
            "documented_errors",
            "entity_format",
            "validation_pattern",
            "format_constraints",
            "invalid_entity_conditions",
        },
    ):
        return True
    context = _normalized_requirement_context(requirement)
    return any(
        cue in context
        for cue in (
            "invalid",
            "incorrect format",
            "rejected",
            "exactly",
            "digits",
            "numbers only",
            "no spaces",
            "dashes",
            "country codes",
            "format",
            "length",
            "pattern",
            "regex",
        )
    )


def _is_missing_entity_requirement(requirement: AtomicRequirement) -> bool:
    return _plans_entity_collection(requirement)


def _is_provided_entity_requirement(requirement: AtomicRequirement) -> bool:
    return _plans_entity_collection(requirement)


def _plans_entity_collection(requirement: AtomicRequirement) -> bool:
    requirement_type = _normalized_requirement_type(requirement)
    if requirement_type == "entity_collection":
        return True
    if _extract_required_entities(requirement):
        return True
    if requirement_type in {"input_parameter", "required_input", "input_collection"}:
        return _documents_entity_collection(requirement)
    return _documents_entity_collection(requirement)


def _extract_required_entities(requirement: AtomicRequirement) -> list[str]:
    if not requirement.metadata:
        return []
    values: list[str] = []
    for key in ("required_entity", "required_entities", "supported_entities", "entity_type"):
        value = requirement.metadata.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif isinstance(value, list):
            values.extend(item.strip() for item in value if isinstance(item, str) and item.strip())
    return values


def _documents_entity_collection(requirement: AtomicRequirement) -> bool:
    context = _normalized_requirement_context(requirement)
    collection_cues = (
        "ask for",
        "prompt for",
        "prompt the user",
        "please enter",
        "collect",
        "request",
        "must be provided",
        "provide",
        "provided",
        "user enters",
    )
    sequencing_cues = (
        "before",
        "required",
        "continue",
        "continuing",
        "lookup",
        "retrieve",
        "proceed",
        "verify",
    )
    actor_cues = ("bot", "chatbot", "assistant", "in chat")
    return (
        any(actor in context for actor in actor_cues)
        and any(cue in context for cue in collection_cues)
        and any(cue in context for cue in sequencing_cues)
    )


def _is_human_handoff_requirement(requirement: AtomicRequirement) -> bool:
    statement = _normalized_statement(requirement)
    return any(
        cue in statement
        for cue in (
            "talk to an agent",
            "transfer the conversation to a human",
            "transfer to human",
            "connect you with an agent",
            "directed to an agent",
        )
    )


def _is_faq_like_requirement(requirement: AtomicRequirement) -> bool:
    return _is_documented_faq_behavior(requirement)


def _is_documented_faq_behavior(requirement: AtomicRequirement) -> bool:
    if _metadata_present_any(requirement, {"faq", "faq_answer", "knowledge_base_answer"}):
        return True
    context = _normalized_requirement_context(requirement)
    return any(
        cue in context
        for cue in (
            "faq",
            "question:",
            "answer:",
            "if the user asks",
            "does not know",
            "do not know",
            "don't know",
            "if the user does not have",
            "alternate support path",
            "unsupported self-service",
            "contact support",
            "knowledge base",
        )
    )


def _supports_adjacent_topic_refusal(requirement: AtomicRequirement) -> bool:
    return _metadata_truthy(requirement, "adjacent_topic_refusal_documented")


def _metadata_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_metadata_text_values(item))
        return values
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(_metadata_text_values(item))
        return values
    return []


def _metadata_present_any(requirement: AtomicRequirement, keys: set[str]) -> bool:
    return any(_metadata_present(requirement, key) for key in keys)


def _metadata_has_key(requirement: AtomicRequirement, normalized_key: str) -> bool:
    if requirement.metadata is None:
        return False
    return any(_normalized_metadata_key(key) == normalized_key for key in requirement.metadata)


def _normalized_metadata_key(key: str) -> str:
    return "".join(str(key).lower().replace("-", "_").replace(" ", "_").split("_"))


def _metadata_value_in(requirement: AtomicRequirement, key: str, allowed: set[str]) -> bool:
    if requirement.metadata is None:
        return False
    value = requirement.metadata.get(key)
    return isinstance(value, str) and value.lower() in allowed


def _metadata_present(requirement: AtomicRequirement, key: str) -> bool:
    if requirement.metadata is None:
        return False
    value = requirement.metadata.get(key)
    return value is not None and value != [] and value != {}


def _metadata_truthy(requirement: AtomicRequirement, key: str) -> bool:
    return bool(requirement.metadata and requirement.metadata.get(key) is True)


def _load_project_config(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
) -> ProjectConfig:
    try:
        return store.load_model(
            ProjectConfig,
            project_id,
            run_id,
            PROJECT_CONFIG_STAGE,
            PROJECT_CONFIG_ARTIFACT_NAME,
        )
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise ProjectConfigArtifactError(f"Failed to load ProjectConfig artifact: {exc}") from exc


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
        raise GovernedLedgerArtifactError(f"Failed to load GovernedRequirementLedger artifact: {exc}") from exc


def _write_obligation_ledger(
    store: ArtifactStore,
    *,
    run_id: str,
    obligation_ledger: TestObligationLedger,
):
    try:
        return store.write_json(
            obligation_ledger.project_id,
            run_id,
            TEST_OBLIGATIONS_STAGE,
            TEST_OBLIGATION_LEDGER_ARTIFACT_NAME,
            obligation_ledger,
        )
    except ArtifactStoreError as exc:
        raise TestObligationPlanningPersistenceError(
            f"Failed to save TestObligationLedger artifact: {exc}"
        ) from exc


def _artifact_context_from_governed_ledger_path(path: Path) -> tuple[Path, str, str]:
    if path.name != "governed_requirement_ledger.json":
        raise GovernedLedgerArtifactError(
            f"GovernedRequirementLedger artifact must be named governed_requirement_ledger.json: {path}"
        )
    if path.parent.name != GOVERNED_REQUIREMENTS_STAGE:
        raise GovernedLedgerArtifactError(
            f"GovernedRequirementLedger artifact must be under {GOVERNED_REQUIREMENTS_STAGE}: {path}"
        )
    run_dir = path.parent.parent
    project_dir = run_dir.parent
    return project_dir.parent, project_dir.name, run_dir.name
