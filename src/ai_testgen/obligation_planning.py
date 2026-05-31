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
                )
            )
            next_obligation_number += 1
            continue
        if not requirement.is_eligible_for_obligation_planning:
            continue

        obligation_types = _obligation_types_for_requirement(requirement, project_config.coverage_policy)
        if not obligation_types:
            obligations.append(
                _obligation_data(
                    requirement,
                    obligation_number=next_obligation_number,
                    obligation_type="skipped_by_policy",
                    status="skipped_by_policy",
                    blocked_reason=POLICY_SKIPPED_REASON,
                )
            )
            next_obligation_number += 1
            continue

        for obligation_type in obligation_types:
            obligations.append(
                _obligation_data(
                    requirement,
                    obligation_number=next_obligation_number,
                    obligation_type=obligation_type,
                    status="planned",
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
    return data


def _obligation_types_for_requirement(
    requirement: AtomicRequirement,
    coverage_policy: dict[str, Any],
) -> list[str]:
    require_positive = _coverage_flag(coverage_policy, "require_positive_tests", default=True)
    require_negative = _coverage_flag(coverage_policy, "require_negative_tests", default=False)
    require_boundary = _coverage_flag(coverage_policy, "require_boundary_tests", default=False)
    requirement_type = " ".join(requirement.requirement_type.lower().split())

    if requirement_type == "entity_collection":
        obligation_types: list[str] = []
        if require_negative:
            obligation_types.append("missing_entity")
        if require_positive:
            obligation_types.append("provided_entity")
        if require_negative and _metadata_present(requirement, "validation_rules"):
            obligation_types.append("invalid_entity")
        return obligation_types

    if requirement_type == "business_rule":
        obligation_types = []
        if require_positive:
            obligation_types.append("positive")
        if require_negative:
            obligation_types.append("negative")
        if require_boundary or _metadata_present(requirement, "threshold"):
            obligation_types.append("boundary")
        return obligation_types

    if requirement_type == "faq_answer":
        obligation_types = []
        if require_positive:
            obligation_types.extend(["direct_question", "paraphrase"])
        if require_negative:
            obligation_types.append("adjacent_topic_negative")
        return obligation_types

    if requirement_type == "api_behavior":
        obligation_types = []
        if require_positive:
            obligation_types.append("success_response")
        if require_negative and _metadata_present(requirement, "documented_errors"):
            obligation_types.append("documented_error_response")
        if _metadata_truthy(requirement, "timeout_unavailable_documented") or _metadata_truthy(
            requirement,
            "timeout_unavailable_approved",
        ):
            obligation_types.append("timeout_unavailable")
        return obligation_types

    obligation_types = []
    if require_positive:
        obligation_types.append("positive")
    if require_negative:
        obligation_types.append("negative")
    if require_boundary:
        obligation_types.append("boundary")
    return obligation_types


def _coverage_flag(coverage_policy: dict[str, Any], key: str, *, default: bool) -> bool:
    value = coverage_policy.get(key, default)
    if type(value) is not bool:
        raise InvalidTestObligationLedgerError(f"coverage_policy.{key} must be a boolean")
    return value


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
