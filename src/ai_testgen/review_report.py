from __future__ import annotations

import os
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_testgen.artifact_store import ArtifactStore, ArtifactStoreError
from ai_testgen.obligation_planning import TEST_OBLIGATION_LEDGER_ARTIFACT_NAME, TEST_OBLIGATIONS_STAGE
from ai_testgen.requirement_governance import (
    GOVERNED_REQUIREMENT_LEDGER_ARTIFACT_NAME,
    GOVERNED_REQUIREMENTS_STAGE,
)
from ai_testgen.schemas import (
    AtomicRequirement,
    AtomicRequirementStatus,
    CoverageReport,
    GovernedRequirementLedger,
    RequirementOrigin,
    ReviewReportMetadata,
    SchemaModel,
    SchemaValidationError,
    TestCase,
    TestCaseStatus,
    TestObligation,
    TestObligationLedger,
    TestObligationStatus,
    ValidatedTestSuite,
)
from ai_testgen.test_validation import (
    COVERAGE_REPORT_ARTIFACT_NAME,
    VALIDATED_TESTS_STAGE,
    VALIDATED_TEST_SUITE_ARTIFACT_NAME,
)


REVIEW_REPORT_STAGE = "09_review_report"
REVIEW_REPORT_ID = "review_001"
REVIEW_REPORT_FILE_NAME = "review_report.md"
REVIEW_REPORT_METADATA_ARTIFACT_NAME = "review_report_metadata"
BLOCKED_OBLIGATION_STATUSES = {
    TestObligationStatus.BLOCKED_MISSING_DATA,
    TestObligationStatus.BLOCKED_UNCLEAR_REQUIREMENT,
}


class ReviewReportError(Exception):
    """Base error for C13 review report generation failures."""


class ValidatedSuiteArtifactError(ReviewReportError):
    """Raised when the input ValidatedTestSuite artifact cannot be used."""


class InvalidReviewReportInputError(ReviewReportError):
    """Raised when C13 input artifacts fail schema or cross-artifact validation."""


class ReviewReportPersistenceError(ReviewReportError):
    """Raised when C13 cannot persist review report outputs."""


@dataclass(frozen=True)
class ReviewReportResult:
    metadata: ReviewReportMetadata
    report_path: Path
    metadata_path: Path
    report_markdown: str


def generate_review_report_from_validated_suite_artifact(
    validated_suite_path: str | Path,
) -> ReviewReportResult:
    suite_path = Path(validated_suite_path)
    artifact_root, project_id, run_id = _artifact_context_from_validated_suite_path(suite_path)
    store = ArtifactStore(artifact_root)

    validated_suite = _load_validated_suite(store, project_id=project_id, run_id=run_id)
    if validated_suite.project_id != project_id:
        raise ValidatedSuiteArtifactError(
            f"ValidatedTestSuite artifact project directory must match project_id "
            f"{validated_suite.project_id}: {suite_path}"
        )

    governed_ledger = _load_governed_ledger(store, project_id=project_id, run_id=run_id)
    obligation_ledger = _load_obligation_ledger(store, project_id=project_id, run_id=run_id)
    coverage_report = _load_coverage_report(store, project_id=project_id, run_id=run_id)
    _validate_review_inputs(governed_ledger, obligation_ledger, validated_suite, coverage_report)

    markdown = build_review_report_markdown(
        governed_ledger,
        obligation_ledger,
        validated_suite,
        coverage_report,
    )
    report_path = _write_report_markdown(store, project_id=project_id, run_id=run_id, markdown=markdown)
    metadata = build_review_report_metadata(
        governed_ledger,
        obligation_ledger,
        validated_suite,
        coverage_report,
        run_id=run_id,
    )
    metadata_artifact = _write_review_metadata(store, run_id=run_id, metadata=metadata)

    return ReviewReportResult(
        metadata=metadata,
        report_path=report_path,
        metadata_path=metadata_artifact.path,
        report_markdown=markdown,
    )


def build_review_report_markdown(
    governed_ledger: GovernedRequirementLedger | Mapping[str, Any],
    obligation_ledger: TestObligationLedger | Mapping[str, Any],
    validated_suite: ValidatedTestSuite | Mapping[str, Any],
    coverage_report: CoverageReport | Mapping[str, Any],
) -> str:
    governed = _coerce_model(GovernedRequirementLedger, governed_ledger)
    obligations = _coerce_model(TestObligationLedger, obligation_ledger)
    suite = _coerce_model(ValidatedTestSuite, validated_suite)
    coverage = _coerce_model(CoverageReport, coverage_report)
    _validate_review_inputs(governed, obligations, suite, coverage)

    lines: list[str] = [
        "# Review Report",
        "",
        f"Project: {suite.project_id}",
        "",
        "## Artifact References",
        "",
        f"- Governed requirements: {governed.governed_ledger_id}",
        f"- Test obligations: {obligations.obligation_ledger_id}",
        f"- Validated suite: {suite.validated_suite_id}",
        f"- Coverage report: {coverage.coverage_report_id}",
        "",
        "## Requirement Status",
        "",
        *_count_table("Status", governed.governance_summary),
        "",
        "## Obligation Status",
        "",
        *_count_table("Status", _obligation_status_counts(obligations.obligations)),
        "",
        "## Validation Summary",
        "",
        *_count_table("Status", suite.validation_summary),
        "",
        "## Coverage Summary",
        "",
        "### Requirements",
        "",
        *_count_table("Metric", coverage.requirement_counts),
        "",
        "### Obligations",
        "",
        *_count_table("Metric", coverage.obligation_counts),
        "",
        "### Tests",
        "",
        *_count_table("Metric", coverage.test_counts),
        "",
        "### Source Chunks",
        "",
        *_count_table("Metric", coverage.source_chunk_counts),
        "",
        "## Coverage Gaps",
        "",
        f"- Uncovered requirements: {_format_ids(coverage.uncovered_requirement_ids)}",
        f"- Uncovered obligations: {_format_ids(coverage.uncovered_obligation_ids)}",
        "",
        "## Conflicts",
        "",
        *_conflict_lines(governed.requirements),
        "",
        "## Approval Needed",
        "",
        *_approval_needed_lines(governed.requirements),
        "",
        "## Blocked Obligations",
        "",
        *_blocked_obligation_lines(obligations.obligations),
        "",
        "## Rejected or Non-Exportable Tests",
        "",
        *_non_exportable_test_lines(suite.test_cases),
    ]
    return "\n".join(lines) + "\n"


def build_review_report_metadata(
    governed_ledger: GovernedRequirementLedger,
    obligation_ledger: TestObligationLedger,
    validated_suite: ValidatedTestSuite,
    coverage_report: CoverageReport,
    *,
    run_id: str,
) -> ReviewReportMetadata:
    summary = {
        "approval_needed_requirements": len(_approval_needed_requirements(governed_ledger.requirements)),
        "blocked_obligations": len(_blocked_obligations(obligation_ledger.obligations)),
        "non_exportable_tests": sum(1 for test_case in validated_suite.test_cases if not test_case.is_exportable),
        "rejected_tests": sum(
            1 for test_case in validated_suite.test_cases if test_case.status == TestCaseStatus.REJECTED
        ),
        "uncovered_obligations": coverage_report.obligation_counts.get("uncovered", 0),
        "uncovered_requirements": coverage_report.requirement_counts.get("uncovered", 0),
    }
    return ReviewReportMetadata.from_dict(
        {
            "review_report_id": REVIEW_REPORT_ID,
            "project_id": validated_suite.project_id,
            "governed_ledger_id": governed_ledger.governed_ledger_id,
            "obligation_ledger_id": obligation_ledger.obligation_ledger_id,
            "validated_suite_id": validated_suite.validated_suite_id,
            "coverage_report_id": coverage_report.coverage_report_id,
            "report_path": _canonical_report_path(validated_suite.project_id, run_id),
            "summary": summary,
        }
    )


def _coerce_model(model_type: type[SchemaModel], value: SchemaModel | Mapping[str, Any]) -> Any:
    if isinstance(value, model_type):
        return value
    if isinstance(value, Mapping):
        return model_type.from_dict(value)
    raise SchemaValidationError(f"{model_type.__name__} input must be a mapping or model")


def _validate_review_inputs(
    governed_ledger: GovernedRequirementLedger,
    obligation_ledger: TestObligationLedger,
    validated_suite: ValidatedTestSuite,
    coverage_report: CoverageReport,
) -> None:
    project_id = validated_suite.project_id
    if governed_ledger.project_id != project_id:
        raise InvalidReviewReportInputError("GovernedRequirementLedger project_id must match ValidatedTestSuite")
    if obligation_ledger.project_id != project_id:
        raise InvalidReviewReportInputError("TestObligationLedger project_id must match ValidatedTestSuite")
    if coverage_report.project_id != project_id:
        raise InvalidReviewReportInputError("CoverageReport project_id must match ValidatedTestSuite")
    if obligation_ledger.governed_ledger_id != governed_ledger.governed_ledger_id:
        raise InvalidReviewReportInputError("TestObligationLedger governed_ledger_id must match GovernedRequirementLedger")
    if coverage_report.validated_suite_id != validated_suite.validated_suite_id:
        raise InvalidReviewReportInputError("CoverageReport validated_suite_id must match ValidatedTestSuite")


def _count_table(first_column: str, counts: Mapping[str, int]) -> list[str]:
    lines = [
        f"| {first_column} | Count |",
        "|---|---:|",
    ]
    for key in sorted(counts):
        lines.append(f"| {key} | {counts[key]} |")
    if not counts:
        lines.append("| none | 0 |")
    return lines


def _obligation_status_counts(obligations: list[TestObligation]) -> dict[str, int]:
    counts = Counter(obligation.status.value for obligation in obligations)
    return dict(counts)


def _format_ids(ids: list[str] | None) -> str:
    if not ids:
        return "none"
    return ", ".join(ids)


def _conflict_lines(requirements: list[AtomicRequirement]) -> list[str]:
    conflicts = [
        requirement
        for requirement in requirements
        if requirement.status == AtomicRequirementStatus.CONFLICTING or requirement.conflicts_with
    ]
    if not conflicts:
        return ["- None"]

    lines: list[str] = []
    for requirement in conflicts:
        conflict_ids = _format_ids(requirement.conflicts_with)
        lines.append(f"- {requirement.requirement_id}: {requirement.statement} Conflicts with: {conflict_ids}")
    return lines


def _approval_needed_requirements(requirements: list[AtomicRequirement]) -> list[AtomicRequirement]:
    approval_needed: list[AtomicRequirement] = []
    for requirement in requirements:
        non_source_pending = (
            requirement.origin != RequirementOrigin.SOURCE_DERIVED
            and requirement.approval_status != "approved"
        )
        explicit_pending = requirement.approval_required is True and requirement.approval_status != "approved"
        status_pending = requirement.status in {
            AtomicRequirementStatus.INFERRED,
            AtomicRequirementStatus.NEEDS_CLARIFICATION,
        }
        if non_source_pending or explicit_pending or status_pending:
            approval_needed.append(requirement)
    return approval_needed


def _approval_needed_lines(requirements: list[AtomicRequirement]) -> list[str]:
    approval_needed = _approval_needed_requirements(requirements)
    if not approval_needed:
        return ["- None"]
    return [
        f"- {requirement.requirement_id} ({requirement.origin.value}, {requirement.status.value}): "
        f"{requirement.statement}"
        for requirement in approval_needed
    ]


def _blocked_obligations(obligations: list[TestObligation]) -> list[TestObligation]:
    return [
        obligation
        for obligation in obligations
        if obligation.status in BLOCKED_OBLIGATION_STATUSES
    ]


def _blocked_obligation_lines(obligations: list[TestObligation]) -> list[str]:
    blocked = _blocked_obligations(obligations)
    if not blocked:
        return ["- None"]
    lines: list[str] = []
    for obligation in blocked:
        reason = obligation.blocked_reason or "No blocked reason recorded."
        lines.append(
            f"- {obligation.obligation_id} ({obligation.status.value}) for "
            f"{obligation.requirement_id}: {reason}"
        )
    return lines


def _non_exportable_test_lines(test_cases: list[TestCase]) -> list[str]:
    non_exportable = [test_case for test_case in test_cases if not test_case.is_exportable]
    if not non_exportable:
        return ["- None"]
    lines: list[str] = []
    for test_case in non_exportable:
        line = (
            f"- {test_case.test_case_id} ({test_case.status.value}, "
            f"export_eligible={test_case.export_eligible}): {test_case.title}."
        )
        if test_case.rejection_reasons:
            line += f" Reasons: {'; '.join(test_case.rejection_reasons)}"
        lines.append(line)
    return lines


def _load_validated_suite(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
) -> ValidatedTestSuite:
    try:
        return store.load_model(
            ValidatedTestSuite,
            project_id,
            run_id,
            VALIDATED_TESTS_STAGE,
            VALIDATED_TEST_SUITE_ARTIFACT_NAME,
        )
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise ValidatedSuiteArtifactError(f"Failed to load ValidatedTestSuite artifact: {exc}") from exc


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
        raise InvalidReviewReportInputError(f"Failed to load GovernedRequirementLedger artifact: {exc}") from exc


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
        raise InvalidReviewReportInputError(f"Failed to load TestObligationLedger artifact: {exc}") from exc


def _load_coverage_report(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
) -> CoverageReport:
    try:
        return store.load_model(
            CoverageReport,
            project_id,
            run_id,
            VALIDATED_TESTS_STAGE,
            COVERAGE_REPORT_ARTIFACT_NAME,
        )
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise InvalidReviewReportInputError(f"Failed to load CoverageReport artifact: {exc}") from exc


def _write_review_metadata(
    store: ArtifactStore,
    *,
    run_id: str,
    metadata: ReviewReportMetadata,
):
    try:
        return store.write_json(
            metadata.project_id,
            run_id,
            REVIEW_REPORT_STAGE,
            REVIEW_REPORT_METADATA_ARTIFACT_NAME,
            metadata,
        )
    except ArtifactStoreError as exc:
        raise ReviewReportPersistenceError(f"Failed to save ReviewReportMetadata artifact: {exc}") from exc


def _write_report_markdown(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
    markdown: str,
) -> Path:
    path = store.artifact_path(project_id, run_id, REVIEW_REPORT_STAGE, "review_report").with_suffix(".md")
    try:
        _write_new_text_file(path, markdown)
    except OSError as exc:
        raise ReviewReportPersistenceError(f"Failed to save review report markdown: {exc}") from exc
    return path


def _write_new_text_file(path: Path, content: str) -> None:
    if path.exists():
        raise ReviewReportPersistenceError(f"Review report already exists: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temp_path = Path(temp_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        if path.exists():
            raise ReviewReportPersistenceError(f"Review report already exists: {path}")
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _canonical_report_path(project_id: str, run_id: str) -> str:
    return f"artifacts/{project_id}/{run_id}/{REVIEW_REPORT_STAGE}/{REVIEW_REPORT_FILE_NAME}"


def _artifact_context_from_validated_suite_path(path: Path) -> tuple[Path, str, str]:
    if path.name != "validated_test_suite.json":
        raise ValidatedSuiteArtifactError(
            f"ValidatedTestSuite artifact must be named validated_test_suite.json: {path}"
        )
    if path.parent.name != VALIDATED_TESTS_STAGE:
        raise ValidatedSuiteArtifactError(
            f"ValidatedTestSuite artifact must be under {VALIDATED_TESTS_STAGE}: {path}"
        )
    run_dir = path.parent.parent
    project_dir = run_dir.parent
    return project_dir.parent, project_dir.name, run_dir.name
