from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_testgen.artifact_store import ArtifactStore, ArtifactStoreError
from ai_testgen.project_config import PROJECT_CONFIG_ARTIFACT_NAME, PROJECT_CONFIG_STAGE
from ai_testgen.schemas import (
    AtomicRequirement,
    AtomicRequirementLedger,
    AtomicRequirementStatus,
    GovernedRequirementLedger,
    ProjectConfig,
    RequirementOrigin,
    SchemaValidationError,
)


ATOMIC_REQUIREMENTS_STAGE = "04_atomic_requirements"
ATOMIC_REQUIREMENT_LEDGER_ARTIFACT_NAME = "atomic_requirement_ledger"
GOVERNED_REQUIREMENTS_STAGE = "05_governed_requirements"
GOVERNED_REQUIREMENT_LEDGER_ARTIFACT_NAME = "governed_requirement_ledger"
GOVERNED_LEDGER_ID = "gov_ledger_001"
GOVERNANCE_POLICY_VERSION = "c09_deterministic_v1"
GOVERNANCE_SUMMARY_KEYS = (
    AtomicRequirementStatus.VALIDATED.value,
    AtomicRequirementStatus.DUPLICATE.value,
    AtomicRequirementStatus.CONFLICTING.value,
    AtomicRequirementStatus.NEEDS_CLARIFICATION.value,
    AtomicRequirementStatus.INFERRED.value,
    AtomicRequirementStatus.OUT_OF_SCOPE.value,
    AtomicRequirementStatus.REJECTED.value,
)
SOURCE_DERIVED_VALIDATABLE_STATUSES = {
    AtomicRequirementStatus.CANDIDATE,
    AtomicRequirementStatus.ATOMIC_DRAFT,
    AtomicRequirementStatus.VALIDATED,
}
TERMINAL_GOVERNANCE_STATUSES = {
    AtomicRequirementStatus.DUPLICATE,
    AtomicRequirementStatus.CONFLICTING,
    AtomicRequirementStatus.OUT_OF_SCOPE,
    AtomicRequirementStatus.REJECTED,
}


class RequirementGovernanceError(Exception):
    """Base error for C09 requirement governance failures."""


class AtomicLedgerArtifactError(RequirementGovernanceError):
    """Raised when the input AtomicRequirementLedger artifact cannot be used."""


class ProjectConfigArtifactError(RequirementGovernanceError):
    """Raised when the required ProjectConfig artifact cannot be used."""


class InvalidGovernedRequirementLedgerError(RequirementGovernanceError):
    """Raised when governed requirements fail C09 validation."""


class RequirementGovernancePersistenceError(RequirementGovernanceError):
    """Raised when C09 cannot persist its output artifact."""


@dataclass(frozen=True)
class RequirementGovernanceResult:
    governed_ledger: GovernedRequirementLedger
    governed_ledger_path: Path


def govern_requirements_from_atomic_ledger_artifact(
    atomic_ledger_path: str | Path,
) -> RequirementGovernanceResult:
    atomic_path = Path(atomic_ledger_path)
    artifact_root, project_id, run_id = _artifact_context_from_atomic_ledger_path(atomic_path)
    store = ArtifactStore(artifact_root)
    project_config = _load_project_config(store, project_id=project_id, run_id=run_id)
    atomic_ledger = _load_atomic_ledger(store, project_id=project_id, run_id=run_id)
    if atomic_ledger.project_id != project_id:
        raise AtomicLedgerArtifactError(
            f"AtomicRequirementLedger artifact project directory must match project_id "
            f"{atomic_ledger.project_id}: {atomic_path}"
        )

    governed_ledger = govern_atomic_requirement_ledger(atomic_ledger, project_config)
    written = _write_governed_ledger(store, run_id=run_id, governed_ledger=governed_ledger)
    return RequirementGovernanceResult(
        governed_ledger=governed_ledger,
        governed_ledger_path=written.path,
    )


def govern_atomic_requirement_ledger(
    atomic_ledger: AtomicRequirementLedger,
    project_config: ProjectConfig,
) -> GovernedRequirementLedger:
    if atomic_ledger.project_id != project_config.project_id:
        raise InvalidGovernedRequirementLedgerError(
            "AtomicRequirementLedger project_id must match ProjectConfig project_id"
        )

    governed_requirements: list[AtomicRequirement] = []
    first_requirement_by_duplicate_key: dict[tuple[str, str], str] = {}

    for requirement in atomic_ledger.requirements:
        data = requirement.to_dict()
        if requirement.conflicts_with or requirement.status == AtomicRequirementStatus.CONFLICTING:
            _apply_status_decision(data, requirement)
        else:
            duplicate_key = _duplicate_key(requirement)
            duplicate_of = first_requirement_by_duplicate_key.get(duplicate_key)
            if duplicate_of is not None and requirement.status != AtomicRequirementStatus.REJECTED:
                data["status"] = AtomicRequirementStatus.DUPLICATE.value
                data["duplicate_of"] = duplicate_of
            else:
                first_requirement_by_duplicate_key.setdefault(duplicate_key, requirement.requirement_id)
                _apply_status_decision(data, requirement)

        _ensure_rejection_rationale(data)
        governed_requirements.append(_governed_requirement_from_dict(data))

    summary = _governance_summary(governed_requirements)
    ledger_data = {
        "governed_ledger_id": GOVERNED_LEDGER_ID,
        "project_id": atomic_ledger.project_id,
        "atomic_ledger_id": atomic_ledger.atomic_ledger_id,
        "requirements": [requirement.to_dict() for requirement in governed_requirements],
        "governance_summary": summary,
        "policy_version": GOVERNANCE_POLICY_VERSION,
    }

    try:
        governed_ledger = GovernedRequirementLedger.from_dict(ledger_data)
    except SchemaValidationError as exc:
        raise InvalidGovernedRequirementLedgerError(
            f"Invalid GovernedRequirementLedger data: {exc}"
        ) from exc

    _validate_governed_ledger(governed_ledger)
    return governed_ledger


def _apply_status_decision(data: dict, requirement: AtomicRequirement) -> None:
    if requirement.status in TERMINAL_GOVERNANCE_STATUSES:
        return

    if requirement.conflicts_with:
        data["status"] = AtomicRequirementStatus.CONFLICTING.value
        return

    if requirement.origin == RequirementOrigin.SOURCE_DERIVED:
        if requirement.status in SOURCE_DERIVED_VALIDATABLE_STATUSES:
            data["status"] = AtomicRequirementStatus.VALIDATED.value
        return

    if requirement.approval_status == "approved":
        data["status"] = AtomicRequirementStatus.VALIDATED.value
    elif requirement.origin == RequirementOrigin.INFERRED:
        data["status"] = AtomicRequirementStatus.INFERRED.value
    else:
        data["status"] = AtomicRequirementStatus.NEEDS_CLARIFICATION.value


def _governed_requirement_from_dict(data: dict) -> AtomicRequirement:
    try:
        return AtomicRequirement.from_dict(data)
    except SchemaValidationError as exc:
        raise InvalidGovernedRequirementLedgerError(f"Invalid governed AtomicRequirement data: {exc}") from exc


def _ensure_rejection_rationale(data: dict) -> None:
    if data.get("status") == AtomicRequirementStatus.REJECTED.value and not data.get("rationale"):
        data["rationale"] = "Rejected before governance without a recorded rationale."


def _validate_governed_ledger(governed_ledger: GovernedRequirementLedger) -> None:
    requirement_ids = {requirement.requirement_id for requirement in governed_ledger.requirements}
    for requirement in governed_ledger.requirements:
        if requirement.duplicate_of is not None and requirement.duplicate_of not in requirement_ids:
            raise InvalidGovernedRequirementLedgerError(
                f"duplicate requirement {requirement.requirement_id} references unknown requirement "
                f"{requirement.duplicate_of}"
            )
        if requirement.status == AtomicRequirementStatus.CONFLICTING and not requirement.conflicts_with:
            raise InvalidGovernedRequirementLedgerError(
                f"conflicting requirement {requirement.requirement_id} must identify conflicts_with"
            )
        if requirement.conflicts_with is not None:
            for conflict_id in requirement.conflicts_with:
                if conflict_id not in requirement_ids:
                    raise InvalidGovernedRequirementLedgerError(
                        f"conflicting requirement {requirement.requirement_id} references unknown requirement "
                        f"{conflict_id}"
                    )
        if (
            requirement.status == AtomicRequirementStatus.VALIDATED
            and not requirement.is_eligible_for_obligation_planning
        ):
            raise InvalidGovernedRequirementLedgerError(
                f"validated requirement {requirement.requirement_id} is not eligible for obligation planning"
            )


def _governance_summary(requirements: list[AtomicRequirement]) -> dict[str, int]:
    summary = {key: 0 for key in GOVERNANCE_SUMMARY_KEYS}
    for requirement in requirements:
        status = requirement.status.value
        if status in summary:
            summary[status] += 1
    return summary


def _duplicate_key(requirement: AtomicRequirement) -> tuple[str, str]:
    return (
        " ".join(requirement.requirement_type.lower().split()),
        _normalized_statement(requirement.statement),
    )


def _normalized_statement(statement: str) -> str:
    return " ".join(statement.lower().strip().rstrip(".!?").split())


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


def _load_atomic_ledger(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
) -> AtomicRequirementLedger:
    try:
        return store.load_model(
            AtomicRequirementLedger,
            project_id,
            run_id,
            ATOMIC_REQUIREMENTS_STAGE,
            ATOMIC_REQUIREMENT_LEDGER_ARTIFACT_NAME,
        )
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise AtomicLedgerArtifactError(f"Failed to load AtomicRequirementLedger artifact: {exc}") from exc


def _write_governed_ledger(
    store: ArtifactStore,
    *,
    run_id: str,
    governed_ledger: GovernedRequirementLedger,
):
    try:
        return store.write_json(
            governed_ledger.project_id,
            run_id,
            GOVERNED_REQUIREMENTS_STAGE,
            GOVERNED_REQUIREMENT_LEDGER_ARTIFACT_NAME,
            governed_ledger,
        )
    except ArtifactStoreError as exc:
        raise RequirementGovernancePersistenceError(
            f"Failed to save GovernedRequirementLedger artifact: {exc}"
        ) from exc


def _artifact_context_from_atomic_ledger_path(path: Path) -> tuple[Path, str, str]:
    if path.name != "atomic_requirement_ledger.json":
        raise AtomicLedgerArtifactError(
            f"AtomicRequirementLedger artifact must be named atomic_requirement_ledger.json: {path}"
        )
    if path.parent.name != ATOMIC_REQUIREMENTS_STAGE:
        raise AtomicLedgerArtifactError(
            f"AtomicRequirementLedger artifact must be under {ATOMIC_REQUIREMENTS_STAGE}: {path}"
        )
    run_dir = path.parent.parent
    project_dir = run_dir.parent
    return project_dir.parent, project_dir.name, run_dir.name
