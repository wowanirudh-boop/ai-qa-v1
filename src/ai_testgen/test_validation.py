from __future__ import annotations

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
    validated_cases = _validated_test_cases(draft.test_cases, governed, obligations)
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
            elif obligation.status not in NORMAL_TESTABLE_OBLIGATION_STATUSES:
                _add_reason(reasons, f"non-exportable obligation {obligation.obligation_id}")

        if not test_case.source_refs:
            _add_reason(reasons, "missing source_refs")
        elif linked_obligations:
            expected_refs = _source_refs_for_obligations(linked_obligations)
            if _normalized_source_refs(test_case.source_refs) != _normalized_source_refs(expected_refs):
                _add_reason(reasons, "source_refs do not match linked obligations")

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


def _json_stable_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().lower()
    return repr(value)


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
