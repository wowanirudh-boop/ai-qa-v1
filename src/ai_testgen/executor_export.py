from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_testgen.artifact_store import ArtifactStore, ArtifactStoreError
from ai_testgen.obligation_planning import TEST_OBLIGATION_LEDGER_ARTIFACT_NAME, TEST_OBLIGATIONS_STAGE
from ai_testgen.project_config import PROJECT_CONFIG_ARTIFACT_NAME, PROJECT_CONFIG_STAGE
from ai_testgen.requirement_governance import (
    GOVERNED_REQUIREMENT_LEDGER_ARTIFACT_NAME,
    GOVERNED_REQUIREMENTS_STAGE,
)
from ai_testgen.schemas import (
    AtomicRequirement,
    AtomicRequirementStatus,
    ExecutorExportPackage,
    GovernedRequirementLedger,
    NORMAL_OBLIGATION_STATUSES,
    ProjectConfig,
    SchemaModel,
    SchemaValidationError,
    SourceRef,
    TestCase,
    TestObligation,
    TestObligationLedger,
    ValidatedTestSuite,
)
from ai_testgen.test_validation import VALIDATED_TESTS_STAGE, VALIDATED_TEST_SUITE_ARTIFACT_NAME
from ai_testgen.validators import validate_executor_export_package


EXECUTOR_EXPORT_STAGE = "10_executor_export"
EXECUTOR_TESTS_ARTIFACT_NAME = "tests"
EXECUTOR_EXPORT_PACKAGE_ARTIFACT_NAME = "executor_export_package"
EXECUTOR_EXPORT_PACKAGE_ID = "export_001"
EXECUTOR_FORMAT_VERSION = "executor_json_v1"


class ExecutorExportError(Exception):
    """Base error for C14 executor export failures."""


class ValidatedSuiteArtifactError(ExecutorExportError):
    """Raised when the input ValidatedTestSuite artifact cannot be used."""


class InvalidExecutorExportInputError(ExecutorExportError):
    """Raised when C14 input artifacts fail schema or cross-artifact validation."""


class InvalidExecutorExportPackageError(ExecutorExportError):
    """Raised when generated C14 output fails validation."""


class ExecutorExportPersistenceError(ExecutorExportError):
    """Raised when C14 cannot persist export outputs."""


@dataclass(frozen=True)
class ExecutorExportResult:
    export_package: ExecutorExportPackage
    executor_tests: dict[str, Any]
    tests_path: Path | None = None
    export_package_path: Path | None = None


def export_tests_from_validated_suite_artifact(
    validated_suite_path: str | Path,
) -> ExecutorExportResult:
    suite_path = Path(validated_suite_path)
    artifact_root, project_id, run_id = _artifact_context_from_validated_suite_path(suite_path)
    store = ArtifactStore(artifact_root)

    validated_suite = _load_validated_suite(store, project_id=project_id, run_id=run_id)
    if validated_suite.project_id != project_id:
        raise ValidatedSuiteArtifactError(
            f"ValidatedTestSuite artifact project directory must match project_id "
            f"{validated_suite.project_id}: {suite_path}"
        )

    project_config = _load_project_config(store, project_id=project_id, run_id=run_id)
    governed_ledger = _load_governed_ledger(store, project_id=project_id, run_id=run_id)
    obligation_ledger = _load_obligation_ledger(store, project_id=project_id, run_id=run_id)

    result = build_executor_export(
        validated_suite,
        governed_ledger,
        obligation_ledger,
        project_config,
        run_id=run_id,
    )
    tests_artifact = _write_executor_tests(
        store,
        project_id=project_id,
        run_id=run_id,
        executor_tests=result.executor_tests,
    )
    package_artifact = _write_export_package(store, run_id=run_id, export_package=result.export_package)
    return ExecutorExportResult(
        export_package=result.export_package,
        executor_tests=result.executor_tests,
        tests_path=tests_artifact.path,
        export_package_path=package_artifact.path,
    )


def build_executor_export(
    validated_suite: ValidatedTestSuite | Mapping[str, Any],
    governed_ledger: GovernedRequirementLedger | Mapping[str, Any],
    obligation_ledger: TestObligationLedger | Mapping[str, Any],
    project_config: ProjectConfig | Mapping[str, Any],
    *,
    run_id: str,
) -> ExecutorExportResult:
    try:
        suite = _coerce_model(ValidatedTestSuite, validated_suite)
        governed = _coerce_model(GovernedRequirementLedger, governed_ledger)
        obligations = _coerce_model(TestObligationLedger, obligation_ledger)
        config = _coerce_model(ProjectConfig, project_config)
    except SchemaValidationError as exc:
        raise InvalidExecutorExportInputError(str(exc)) from exc

    _validate_export_inputs(suite, governed, obligations, config)

    requirements_by_id = {
        requirement.requirement_id: requirement
        for requirement in governed.requirements
    }
    obligations_by_id = {
        obligation.obligation_id: obligation
        for obligation in obligations.obligations
    }
    exportable_tests = [
        test_case
        for test_case in suite.test_cases
        if _passes_final_export_checks(test_case, requirements_by_id, obligations_by_id)
    ]
    executor_tests = _executor_tests_document(suite, config, exportable_tests)
    export_package = _build_export_package(suite, exportable_tests, run_id=run_id)

    try:
        validate_executor_export_package(export_package, suite)
    except SchemaValidationError as exc:
        raise InvalidExecutorExportPackageError(f"Invalid ExecutorExportPackage data: {exc}") from exc

    return ExecutorExportResult(
        export_package=export_package,
        executor_tests=executor_tests,
    )


def _coerce_model(model_type: type[SchemaModel], value: SchemaModel | Mapping[str, Any]) -> Any:
    if isinstance(value, model_type):
        return value
    if isinstance(value, Mapping):
        return model_type.from_dict(value)
    raise SchemaValidationError(f"{model_type.__name__} input must be a mapping or model")


def _validate_export_inputs(
    validated_suite: ValidatedTestSuite,
    governed_ledger: GovernedRequirementLedger,
    obligation_ledger: TestObligationLedger,
    project_config: ProjectConfig,
) -> None:
    project_id = validated_suite.project_id
    if project_config.project_id != project_id:
        raise InvalidExecutorExportInputError("ProjectConfig project_id must match ValidatedTestSuite")
    if governed_ledger.project_id != project_id:
        raise InvalidExecutorExportInputError("GovernedRequirementLedger project_id must match ValidatedTestSuite")
    if obligation_ledger.project_id != project_id:
        raise InvalidExecutorExportInputError("TestObligationLedger project_id must match ValidatedTestSuite")
    if obligation_ledger.governed_ledger_id != governed_ledger.governed_ledger_id:
        raise InvalidExecutorExportInputError("TestObligationLedger governed_ledger_id must match GovernedRequirementLedger")


def _passes_final_export_checks(
    test_case: TestCase,
    requirements_by_id: dict[str, AtomicRequirement],
    obligations_by_id: dict[str, TestObligation],
) -> bool:
    if not test_case.is_exportable:
        return False
    if not test_case.source_refs:
        return False

    linked_requirements: list[AtomicRequirement] = []
    for requirement_id in test_case.requirement_ids:
        requirement = requirements_by_id.get(requirement_id)
        if requirement is None or not _requirement_is_exportable(requirement):
            return False
        linked_requirements.append(requirement)

    linked_obligations: list[TestObligation] = []
    for obligation_id in test_case.obligation_ids:
        obligation = obligations_by_id.get(obligation_id)
        if obligation is None or obligation.status not in NORMAL_OBLIGATION_STATUSES:
            return False
        linked_obligations.append(obligation)

    obligation_requirement_ids = _requirement_ids_for_obligations(linked_obligations)
    if set(test_case.requirement_ids) != set(obligation_requirement_ids):
        return False

    expected_refs = _source_refs_for_obligations(linked_obligations)
    return _normalized_source_refs(test_case.source_refs) == _normalized_source_refs(expected_refs)


def _requirement_is_exportable(requirement: AtomicRequirement) -> bool:
    if requirement.status != AtomicRequirementStatus.VALIDATED:
        return False
    if requirement.requires_approval_before_export and requirement.approval_status != "approved":
        return False
    return True


def _executor_tests_document(
    validated_suite: ValidatedTestSuite,
    project_config: ProjectConfig,
    test_cases: list[TestCase],
) -> dict[str, Any]:
    return {
        "format_version": EXECUTOR_FORMAT_VERSION,
        "project_id": validated_suite.project_id,
        "validated_suite_id": validated_suite.validated_suite_id,
        "bot_name": project_config.bot_name,
        "target_url": project_config.target_url,
        "tests": [_executor_test_record(test_case) for test_case in test_cases],
    }


def _executor_test_record(test_case: TestCase) -> dict[str, Any]:
    record: dict[str, Any] = {
        "test_case_id": test_case.test_case_id,
        "title": test_case.title,
        "requirement_ids": list(test_case.requirement_ids),
        "obligation_ids": list(test_case.obligation_ids),
        "source_refs": [source_ref.to_dict() for source_ref in (test_case.source_refs or [])],
        "turns": [turn.to_dict() for turn in test_case.turns],
        "assertions": [assertion.to_dict() for assertion in test_case.assertions],
    }
    if test_case.priority is not None:
        record["priority"] = test_case.priority
    if test_case.tags is not None:
        record["tags"] = list(test_case.tags)
    return record


def _build_export_package(
    validated_suite: ValidatedTestSuite,
    exported_tests: list[TestCase],
    *,
    run_id: str,
) -> ExecutorExportPackage:
    try:
        return ExecutorExportPackage.from_dict(
            {
                "export_package_id": EXECUTOR_EXPORT_PACKAGE_ID,
                "project_id": validated_suite.project_id,
                "validated_suite_id": validated_suite.validated_suite_id,
                "exported_test_case_ids": [test_case.test_case_id for test_case in exported_tests],
                "format": "json",
                "output_paths": [_canonical_tests_path(validated_suite.project_id, run_id)],
                "eligibility_summary": {
                    "eligible": len(exported_tests),
                    "excluded": len(validated_suite.test_cases) - len(exported_tests),
                },
            }
        )
    except SchemaValidationError as exc:
        raise InvalidExecutorExportPackageError(f"Invalid ExecutorExportPackage data: {exc}") from exc


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
        raise InvalidExecutorExportInputError(f"Failed to load ProjectConfig artifact: {exc}") from exc


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
        raise InvalidExecutorExportInputError(f"Failed to load GovernedRequirementLedger artifact: {exc}") from exc


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
        raise InvalidExecutorExportInputError(f"Failed to load TestObligationLedger artifact: {exc}") from exc


def _write_executor_tests(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
    executor_tests: dict[str, Any],
):
    try:
        return store.write_json(
            project_id,
            run_id,
            EXECUTOR_EXPORT_STAGE,
            EXECUTOR_TESTS_ARTIFACT_NAME,
            executor_tests,
        )
    except ArtifactStoreError as exc:
        raise ExecutorExportPersistenceError(f"Failed to save executor tests artifact: {exc}") from exc


def _write_export_package(
    store: ArtifactStore,
    *,
    run_id: str,
    export_package: ExecutorExportPackage,
):
    try:
        return store.write_json(
            export_package.project_id,
            run_id,
            EXECUTOR_EXPORT_STAGE,
            EXECUTOR_EXPORT_PACKAGE_ARTIFACT_NAME,
            export_package,
        )
    except ArtifactStoreError as exc:
        raise ExecutorExportPersistenceError(f"Failed to save ExecutorExportPackage artifact: {exc}") from exc


def _canonical_tests_path(project_id: str, run_id: str) -> str:
    return f"artifacts/{project_id}/{run_id}/{EXECUTOR_EXPORT_STAGE}/tests.json"


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
