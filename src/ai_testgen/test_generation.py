from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import count
from pathlib import Path

from ai_testgen.artifact_store import ArtifactStore, ArtifactStoreError
from ai_testgen.obligation_planning import TEST_OBLIGATION_LEDGER_ARTIFACT_NAME, TEST_OBLIGATIONS_STAGE
from ai_testgen.requirement_governance import (
    GOVERNED_REQUIREMENT_LEDGER_ARTIFACT_NAME,
    GOVERNED_REQUIREMENTS_STAGE,
)
from ai_testgen.schemas import (
    DraftTestSuite,
    GovernedRequirementLedger,
    SchemaValidationError,
    SkillDefinition,
    SkillRunRecord,
    SourceRef,
    TestCase,
    TestCaseStatus,
    TestObligation,
    TestObligationLedger,
    TestObligationStatus,
)
from ai_testgen.skill_runtime import (
    InvalidSkillDefinitionError,
    SkillExecutionError,
    SkillRuntime,
    SkillRuntimeError,
    load_skill_definition,
    validate_skill_definition,
)
from ai_testgen.validators import validate_obligation_links, validate_test_case_links


DRAFT_TESTS_STAGE = "07_draft_tests"
DRAFT_TEST_SUITE_ARTIFACT_NAME = "draft_test_suite"
RAW_DRAFT_TEST_SUITE_ARTIFACT_NAME = "draft_test_suite_skill_output"
ORACLE_DRAFT_TEST_SUITE_ARTIFACT_NAME = "draft_test_suite_oracle_output"
TEST_GENERATION_INPUT_ARTIFACT_NAME = "test_generation_input"
DEFAULT_TEST_CASE_WRITER_SKILL_DEFINITION_PATH = Path("skills") / "test_case_writer_v1.json"
DEFAULT_ORACLE_GENERATOR_SKILL_DEFINITION_PATH = Path("skills") / "oracle_generator_v1.json"
TEST_CASE_WRITER_INPUT_CONTRACT = "TestObligationLedger"
TEST_CASE_WRITER_OUTPUT_CONTRACT = "DraftTestSuite"
ORACLE_GENERATOR_INPUT_CONTRACT = "DraftTestSuite"
ORACLE_GENERATOR_OUTPUT_CONTRACT = "DraftTestSuite"
DRAFT_SUITE_ID = "draft_suite_001"


class TestGenerationError(Exception):
    """Base error for C11 test generation failures."""


class TestObligationLedgerArtifactError(TestGenerationError):
    """Raised when the input TestObligationLedger artifact cannot be used."""


class GovernedLedgerArtifactError(TestGenerationError):
    """Raised when the linked GovernedRequirementLedger artifact cannot be used."""


class InvalidTestGenerationSkillError(TestGenerationError):
    """Raised when a C11 SkillDefinition does not match expected contracts."""


class TestGenerationSkillError(TestGenerationError):
    """Raised when the Skill Runtime fails a C11 skill run."""


class InvalidDraftTestSuiteError(TestGenerationError):
    """Raised when generated draft tests fail C11 validation."""


class TestGenerationPersistenceError(TestGenerationError):
    """Raised when C11 cannot persist its artifacts."""


@dataclass(frozen=True)
class TestGenerationResult:
    draft_suite: DraftTestSuite
    draft_suite_path: Path
    skill_run_record: SkillRunRecord
    skill_run_record_path: Path
    skill_run_records: list[SkillRunRecord]
    skill_run_record_paths: list[Path]


def generate_tests_from_obligation_ledger_artifact(
    obligation_ledger_path: str | Path,
    test_case_writer_skill_definition: SkillDefinition | str | Path | None = None,
    oracle_generator_skill_definition: SkillDefinition | str | Path | None = None,
    *,
    skill_runtime: SkillRuntime | None = None,
    skill_run_id: str | None = None,
    max_obligations_per_skill_run: int = 1,
) -> TestGenerationResult:
    if type(max_obligations_per_skill_run) is not int or max_obligations_per_skill_run < 1:
        raise TestObligationLedgerArtifactError("max_obligations_per_skill_run must be a positive integer")

    obligation_path = Path(obligation_ledger_path)
    artifact_root, project_id, run_id = _artifact_context_from_obligation_ledger_path(obligation_path)
    store = ArtifactStore(artifact_root)
    obligation_ledger = _load_obligation_ledger(store, project_id=project_id, run_id=run_id)
    if obligation_ledger.project_id != project_id:
        raise TestObligationLedgerArtifactError(
            f"TestObligationLedger artifact project directory must match project_id "
            f"{obligation_ledger.project_id}: {obligation_path}"
        )
    governed_ledger = _load_governed_ledger(store, project_id=project_id, run_id=run_id)
    _validate_obligation_ledger_against_governed(obligation_ledger, governed_ledger)

    writer_definition = _load_test_generation_skill_definition(
        DEFAULT_TEST_CASE_WRITER_SKILL_DEFINITION_PATH
        if test_case_writer_skill_definition is None
        else test_case_writer_skill_definition,
        expected_input_contract=TEST_CASE_WRITER_INPUT_CONTRACT,
        expected_output_contract=TEST_CASE_WRITER_OUTPUT_CONTRACT,
    )
    oracle_definition = _load_test_generation_skill_definition(
        DEFAULT_ORACLE_GENERATOR_SKILL_DEFINITION_PATH
        if oracle_generator_skill_definition is None
        else oracle_generator_skill_definition,
        expected_input_contract=ORACLE_GENERATOR_INPUT_CONTRACT,
        expected_output_contract=ORACLE_GENERATOR_OUTPUT_CONTRACT,
    )

    runtime = skill_runtime or SkillRuntime(artifact_root=artifact_root)
    eligible_obligations = _eligible_obligations(obligation_ledger)
    raw_draft_suites: list[DraftTestSuite] = []
    skill_run_records: list[SkillRunRecord] = []
    batches = _obligation_batches(eligible_obligations, max_obligations_per_skill_run)

    for batch_index, batch in enumerate(batches, start=1):
        bounded_obligations = _obligation_ledger_with_obligations(
            obligation_ledger,
            batch,
            governed_ledger,
        )
        bounded_artifact = _write_generation_input_obligations(
            store,
            run_id=run_id,
            obligation_ledger=bounded_obligations,
        )
        writer_output_path, writer_output_version = _next_artifact_path(
            store,
            project_id,
            run_id,
            DRAFT_TESTS_STAGE,
            RAW_DRAFT_TEST_SUITE_ARTIFACT_NAME,
        )
        writer_run_id = _skill_run_id_for_step(
            store,
            project_id,
            run_id,
            skill_run_id,
            batch_index,
            len(batches),
            "writer",
        )

        try:
            writer_record = runtime.run_skill(
                writer_definition,
                input_artifact_paths=[bounded_artifact.path],
                output_artifact_paths=[writer_output_path],
                skill_run_id=writer_run_id,
            )
        except SkillExecutionError as exc:
            raise TestGenerationSkillError(f"Test case writing skill failed: {exc}") from exc

        writer_suite = _load_draft_suite(
            store,
            project_id=project_id,
            run_id=run_id,
            artifact_name=RAW_DRAFT_TEST_SUITE_ARTIFACT_NAME,
            version=writer_output_version,
        )
        validate_draft_suite_against_inputs(writer_suite, bounded_obligations, governed_ledger)

        oracle_output_path, oracle_output_version = _next_artifact_path(
            store,
            project_id,
            run_id,
            DRAFT_TESTS_STAGE,
            ORACLE_DRAFT_TEST_SUITE_ARTIFACT_NAME,
        )
        oracle_run_id = _skill_run_id_for_step(
            store,
            project_id,
            run_id,
            skill_run_id,
            batch_index,
            len(batches),
            "oracle",
        )

        try:
            oracle_record = runtime.run_skill(
                oracle_definition,
                input_artifact_paths=[writer_output_path],
                output_artifact_paths=[oracle_output_path],
                skill_run_id=oracle_run_id,
            )
        except SkillExecutionError as exc:
            raise TestGenerationSkillError(f"Oracle generation skill failed: {exc}") from exc

        oracle_suite = _load_draft_suite(
            store,
            project_id=project_id,
            run_id=run_id,
            artifact_name=ORACLE_DRAFT_TEST_SUITE_ARTIFACT_NAME,
            version=oracle_output_version,
        )
        validate_draft_suite_against_inputs(oracle_suite, bounded_obligations, governed_ledger)
        raw_draft_suites.append(oracle_suite)
        skill_run_records.extend([writer_record, oracle_record])

    draft_suite = _merge_draft_suites_with_deterministic_ids(
        raw_draft_suites,
        obligation_ledger,
        skill_run_ids=[record.skill_run_id for record in skill_run_records],
    )
    validate_draft_suite_against_inputs(draft_suite, obligation_ledger, governed_ledger)
    written = _write_draft_suite(store, run_id=run_id, draft_suite=draft_suite)
    skill_run_record_paths = [
        store.artifact_path(project_id, run_id, "skill_runs", record.skill_run_id)
        for record in skill_run_records
    ]

    return TestGenerationResult(
        draft_suite=draft_suite,
        draft_suite_path=written.path,
        skill_run_record=skill_run_records[0],
        skill_run_record_path=skill_run_record_paths[0],
        skill_run_records=skill_run_records,
        skill_run_record_paths=skill_run_record_paths,
    )


def validate_draft_suite_against_inputs(
    draft_suite: DraftTestSuite,
    obligation_ledger: TestObligationLedger,
    governed_ledger: GovernedRequirementLedger,
) -> None:
    if draft_suite.project_id != obligation_ledger.project_id:
        raise InvalidDraftTestSuiteError("DraftTestSuite project_id must match TestObligationLedger")
    if draft_suite.obligation_ledger_id != obligation_ledger.obligation_ledger_id:
        raise InvalidDraftTestSuiteError("DraftTestSuite obligation_ledger_id must match TestObligationLedger")
    _validate_obligation_ledger_against_governed(obligation_ledger, governed_ledger)

    try:
        validate_test_case_links(draft_suite.test_cases, governed_ledger.requirements, obligation_ledger.obligations)
    except SchemaValidationError as exc:
        raise InvalidDraftTestSuiteError(str(exc)) from exc

    obligations_by_id = {obligation.obligation_id: obligation for obligation in obligation_ledger.obligations}
    for test_case in draft_suite.test_cases:
        if test_case.status != TestCaseStatus.DRAFT:
            raise InvalidDraftTestSuiteError(
                f"test case {test_case.test_case_id} must remain draft in C11 output"
            )
        if test_case.export_eligible is not None:
            raise InvalidDraftTestSuiteError(
                f"test case {test_case.test_case_id} must not set export_eligible in C11"
            )
        expected_requirement_ids = _requirement_ids_for_test_case(test_case, obligations_by_id)
        if set(test_case.requirement_ids) != set(expected_requirement_ids):
            raise InvalidDraftTestSuiteError(
                f"test case {test_case.test_case_id} requirement_ids must match linked obligations"
            )
        expected_refs = _source_refs_for_test_case(test_case, obligations_by_id)
        if _normalized_source_refs(test_case.source_refs) != _normalized_source_refs(expected_refs):
            raise InvalidDraftTestSuiteError(
                f"test case {test_case.test_case_id} source_refs must match linked obligations"
            )


def _validate_obligation_ledger_against_governed(
    obligation_ledger: TestObligationLedger,
    governed_ledger: GovernedRequirementLedger,
) -> None:
    if obligation_ledger.project_id != governed_ledger.project_id:
        raise InvalidDraftTestSuiteError(
            "TestObligationLedger project_id must match GovernedRequirementLedger project_id"
        )
    if obligation_ledger.governed_ledger_id != governed_ledger.governed_ledger_id:
        raise InvalidDraftTestSuiteError(
            "TestObligationLedger governed_ledger_id must match GovernedRequirementLedger"
        )
    try:
        validate_obligation_links(obligation_ledger.obligations, governed_ledger.requirements)
    except SchemaValidationError as exc:
        raise InvalidDraftTestSuiteError(str(exc)) from exc


def _load_test_generation_skill_definition(
    skill_definition: SkillDefinition | str | Path,
    *,
    expected_input_contract: str,
    expected_output_contract: str,
) -> SkillDefinition:
    try:
        definition = (
            skill_definition
            if isinstance(skill_definition, SkillDefinition)
            else load_skill_definition(skill_definition)
        )
        validated = validate_skill_definition(definition)
    except (InvalidSkillDefinitionError, SchemaValidationError, SkillRuntimeError) as exc:
        raise InvalidTestGenerationSkillError(f"Invalid test generation SkillDefinition: {exc}") from exc

    if validated.input_contract != expected_input_contract:
        raise InvalidTestGenerationSkillError(
            f"Test generation skill input_contract must be {expected_input_contract}"
        )
    if validated.output_contract != expected_output_contract:
        raise InvalidTestGenerationSkillError(
            f"Test generation skill output_contract must be {expected_output_contract}"
        )
    return validated


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
        raise TestObligationLedgerArtifactError(f"Failed to load TestObligationLedger artifact: {exc}") from exc


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


def _load_draft_suite(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
    artifact_name: str,
    version: int,
) -> DraftTestSuite:
    try:
        return store.load_model(
            DraftTestSuite,
            project_id,
            run_id,
            DRAFT_TESTS_STAGE,
            artifact_name,
            version=version,
        )
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise InvalidDraftTestSuiteError(f"Failed to load DraftTestSuite artifact: {exc}") from exc


def _write_generation_input_obligations(
    store: ArtifactStore,
    *,
    run_id: str,
    obligation_ledger: TestObligationLedger,
):
    try:
        return store.write_json(
            obligation_ledger.project_id,
            run_id,
            DRAFT_TESTS_STAGE,
            TEST_GENERATION_INPUT_ARTIFACT_NAME,
            obligation_ledger,
        )
    except ArtifactStoreError as exc:
        raise TestGenerationPersistenceError(f"Failed to save test generation input artifact: {exc}") from exc


def _write_draft_suite(
    store: ArtifactStore,
    *,
    run_id: str,
    draft_suite: DraftTestSuite,
):
    try:
        return store.write_json(
            draft_suite.project_id,
            run_id,
            DRAFT_TESTS_STAGE,
            DRAFT_TEST_SUITE_ARTIFACT_NAME,
            draft_suite,
        )
    except ArtifactStoreError as exc:
        raise TestGenerationPersistenceError(f"Failed to save DraftTestSuite artifact: {exc}") from exc


def _eligible_obligations(obligation_ledger: TestObligationLedger) -> list[TestObligation]:
    obligations = [
        obligation
        for obligation in obligation_ledger.obligations
        if obligation.status == TestObligationStatus.PLANNED
    ]
    if not obligations:
        raise TestObligationLedgerArtifactError("No planned test obligations are eligible for generation")
    return obligations


def _obligation_ledger_with_obligations(
    obligation_ledger: TestObligationLedger,
    obligations: list[TestObligation],
    governed_ledger: GovernedRequirementLedger,
) -> TestObligationLedger:
    linked_requirements = _linked_requirements_for_obligations(obligations, governed_ledger)
    data = obligation_ledger.to_dict()
    data["obligations"] = [obligation.to_dict() for obligation in obligations]
    data["metadata"] = {
        "linked_requirements": [requirement.to_dict() for requirement in linked_requirements],
    }
    try:
        return TestObligationLedger.from_dict(data)
    except SchemaValidationError as exc:
        raise TestObligationLedgerArtifactError(f"Invalid bounded TestObligationLedger data: {exc}") from exc


def _linked_requirements_for_obligations(
    obligations: list[TestObligation],
    governed_ledger: GovernedRequirementLedger,
):
    requirements_by_id = {
        requirement.requirement_id: requirement
        for requirement in governed_ledger.requirements
    }
    linked = []
    seen: set[str] = set()
    for obligation in obligations:
        requirement = requirements_by_id.get(obligation.requirement_id)
        if requirement is None:
            raise InvalidDraftTestSuiteError(
                f"obligation {obligation.obligation_id} references unknown requirement "
                f"{obligation.requirement_id}"
            )
        if requirement.requirement_id not in seen:
            linked.append(requirement)
            seen.add(requirement.requirement_id)
    return linked


def _merge_draft_suites_with_deterministic_ids(
    draft_suites: list[DraftTestSuite],
    obligation_ledger: TestObligationLedger,
    *,
    skill_run_ids: list[str],
) -> DraftTestSuite:
    if not draft_suites:
        raise InvalidDraftTestSuiteError("No DraftTestSuite outputs to merge")

    test_cases: list[dict] = []
    next_test_case_id = count(1)
    obligations_by_id = {obligation.obligation_id: obligation for obligation in obligation_ledger.obligations}
    for draft_suite in draft_suites:
        if draft_suite.project_id != obligation_ledger.project_id:
            raise InvalidDraftTestSuiteError("DraftTestSuite project_id values must match TestObligationLedger")
        if draft_suite.obligation_ledger_id != obligation_ledger.obligation_ledger_id:
            raise InvalidDraftTestSuiteError(
                "DraftTestSuite obligation_ledger_id values must match TestObligationLedger"
            )
        for test_case in draft_suite.test_cases:
            test_cases.append(
                _test_case_with_deterministic_ids(
                    test_case,
                    test_case_number=next(next_test_case_id),
                    obligations_by_id=obligations_by_id,
                )
            )

    try:
        return DraftTestSuite.from_dict(
            {
                "draft_suite_id": DRAFT_SUITE_ID,
                "project_id": obligation_ledger.project_id,
                "obligation_ledger_id": obligation_ledger.obligation_ledger_id,
                "test_cases": test_cases,
                "skill_run_ids": skill_run_ids,
            }
        )
    except SchemaValidationError as exc:
        raise InvalidDraftTestSuiteError(f"Invalid deterministic DraftTestSuite data: {exc}") from exc


def _test_case_with_deterministic_ids(
    test_case: TestCase,
    *,
    test_case_number: int,
    obligations_by_id: dict[str, TestObligation],
) -> dict:
    data = test_case.to_dict()
    data["test_case_id"] = f"tc_{test_case_number:03d}"
    data["status"] = TestCaseStatus.DRAFT.value
    data["requirement_ids"] = _requirement_ids_for_test_case(test_case, obligations_by_id)
    data["source_refs"] = [source_ref.to_dict() for source_ref in _source_refs_for_test_case(test_case, obligations_by_id)]
    data.pop("export_eligible", None)
    for index, turn in enumerate(data["turns"], start=1):
        turn["turn_id"] = f"turn_{index:03d}"
    for index, item in enumerate(data["assertions"], start=1):
        item["assertion_id"] = f"assert_{index:03d}"
    return data


def _requirement_ids_for_test_case(
    test_case: TestCase,
    obligations_by_id: dict[str, TestObligation],
) -> list[str]:
    requirement_ids: list[str] = []
    for obligation_id in test_case.obligation_ids:
        obligation = obligations_by_id[obligation_id]
        if obligation.requirement_id not in requirement_ids:
            requirement_ids.append(obligation.requirement_id)
    return requirement_ids


def _source_refs_for_test_case(
    test_case: TestCase,
    obligations_by_id: dict[str, TestObligation],
) -> list[SourceRef]:
    source_refs: list[SourceRef] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for obligation_id in test_case.obligation_ids:
        for source_ref in obligations_by_id[obligation_id].source_refs:
            normalized = tuple(sorted(source_ref.to_dict().items()))
            if normalized not in seen:
                source_refs.append(source_ref)
                seen.add(normalized)
    return source_refs


def _normalized_source_refs(source_refs: Iterable[SourceRef] | None) -> list[tuple[tuple[str, str], ...]]:
    return sorted(
        tuple(sorted(source_ref.to_dict().items()))
        for source_ref in (source_refs or [])
    )


def _artifact_context_from_obligation_ledger_path(path: Path) -> tuple[Path, str, str]:
    if path.name != "test_obligation_ledger.json":
        raise TestObligationLedgerArtifactError(
            f"TestObligationLedger artifact must be named test_obligation_ledger.json: {path}"
        )
    if path.parent.name != TEST_OBLIGATIONS_STAGE:
        raise TestObligationLedgerArtifactError(
            f"TestObligationLedger artifact must be under {TEST_OBLIGATIONS_STAGE}: {path}"
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


def _skill_run_id_for_step(
    store: ArtifactStore,
    project_id: str,
    run_id: str,
    requested_skill_run_id: str | None,
    batch_index: int,
    batch_count: int,
    step: str,
) -> str:
    if requested_skill_run_id is None:
        return _next_skill_run_id(store, project_id, run_id)
    if batch_count == 1:
        return requested_skill_run_id if step == "writer" else f"{requested_skill_run_id}_oracle"
    return f"{requested_skill_run_id}_{batch_index:03d}_{step}"


def _obligation_batches(obligations: list[TestObligation], batch_size: int) -> list[list[TestObligation]]:
    return [
        obligations[index:index + batch_size]
        for index in range(0, len(obligations), batch_size)
    ]
