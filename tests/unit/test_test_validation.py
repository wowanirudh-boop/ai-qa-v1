import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_testgen.cli as cli
import ai_testgen.test_validation as test_validation
from ai_testgen.artifact_store import ArtifactStore
from ai_testgen.schemas import CoverageReport, ValidatedTestSuite
from ai_testgen.test_validation import (
    DraftTestSuiteArtifactError,
    InvalidTestValidationInputError,
    validate_draft_suite,
    validate_tests_from_draft_suite_artifact,
)


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "test_validation_coverage"


def source_ref(chunk_id: str = "chunk_001", document_id: str = "doc_001") -> dict:
    return {"document_id": document_id, "chunk_id": chunk_id}


def source_chunk(**overrides: object) -> dict:
    data = {
        "chunk_id": "chunk_001",
        "document_id": "doc_001",
        "text": "The bot must ask for an order number before showing order status.",
        "checksum": "sha256:chunk001",
        "processing_status": "requirements_extracted",
    }
    data.update(overrides)
    return data


def source_package_data(**overrides: object) -> dict:
    data = {
        "source_package_id": "source_pkg_001",
        "project_id": "demo_chatbot",
        "document_ids": ["doc_001"],
        "chunks": [
            source_chunk(),
            source_chunk(
                chunk_id="chunk_002",
                text="Background support policy context.",
                checksum="sha256:chunk002",
                processing_status="non_testable_context",
            ),
        ],
        "checksum": "sha256:pkg001",
    }
    data.update(overrides)
    return data


def governed_requirement(**overrides: object) -> dict:
    data = {
        "requirement_id": "req_001",
        "statement": "The bot must ask for an order number before showing order status.",
        "requirement_type": "functional",
        "status": "validated",
        "origin": "source_derived",
        "source_refs": [source_ref()],
        "candidate_ids": ["cand_001"],
    }
    data.update(overrides)
    return data


def governed_ledger_data(**overrides: object) -> dict:
    data = {
        "governed_ledger_id": "gov_ledger_001",
        "project_id": "demo_chatbot",
        "atomic_ledger_id": "atomic_ledger_001",
        "requirements": [governed_requirement()],
        "governance_summary": {
            "conflicting": 0,
            "duplicate": 0,
            "inferred": 0,
            "needs_clarification": 0,
            "out_of_scope": 0,
            "rejected": 0,
            "validated": 1,
        },
    }
    data.update(overrides)
    return data


def obligation_data(**overrides: object) -> dict:
    data = {
        "obligation_id": "obl_001",
        "requirement_id": "req_001",
        "obligation_type": "positive",
        "status": "planned",
        "source_refs": [source_ref()],
    }
    data.update(overrides)
    return data


def obligation_ledger_data(**overrides: object) -> dict:
    data = {
        "obligation_ledger_id": "obl_ledger_001",
        "project_id": "demo_chatbot",
        "governed_ledger_id": "gov_ledger_001",
        "obligations": [obligation_data()],
    }
    data.update(overrides)
    return data


def conversation_turn(**overrides: object) -> dict:
    data = {
        "turn_id": "turn_001",
        "speaker": "user",
        "text": "Where is my order?",
    }
    data.update(overrides)
    return data


def assertion(**overrides: object) -> dict:
    data = {
        "assertion_id": "assert_001",
        "assertion_type": "bot_response_contains_request",
        "target": "bot.final_response",
        "expected": "The bot asks for the order number before providing status.",
    }
    data.update(overrides)
    return data


def draft_test_case_data(**overrides: object) -> dict:
    data = {
        "test_case_id": "tc_001",
        "title": "Order status requires order number",
        "status": "draft",
        "requirement_ids": ["req_001"],
        "obligation_ids": ["obl_001"],
        "source_refs": [source_ref()],
        "turns": [conversation_turn()],
        "assertions": [assertion()],
    }
    data.update(overrides)
    return data


def draft_suite_data(**overrides: object) -> dict:
    data = {
        "draft_suite_id": "draft_suite_001",
        "project_id": "demo_chatbot",
        "obligation_ledger_id": "obl_ledger_001",
        "test_cases": [draft_test_case_data()],
    }
    data.update(overrides)
    return data


def stable_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_governed_ledger(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "05_governed_requirements",
        "governed_requirement_ledger",
        data or governed_ledger_data(),
    )


def write_obligation_ledger(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "06_test_obligations",
        "test_obligation_ledger",
        data or obligation_ledger_data(),
    )


def write_source_package(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "02_source_package",
        "source_package",
        data or source_package_data(),
    )


def write_draft_suite(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "07_draft_tests",
        "draft_test_suite",
        data or draft_suite_data(),
    )


def test_valid_draft_test_becomes_valid_and_export_eligible():
    result = validate_draft_suite(
        draft_suite_data(),
        governed_ledger_data(),
        obligation_ledger_data(),
        source_package_data(),
    )

    validated = result.validated_suite.to_dict()

    assert validated["test_cases"][0]["status"] == "valid"
    assert validated["test_cases"][0]["export_eligible"] is True
    assert validated["validation_summary"] == {
        "valid": 1,
        "needs_review": 0,
        "rejected": 0,
        "export_eligible": 1,
    }
    assert result.coverage_report.to_dict()["test_counts"] == {
        "total": 1,
        "valid": 1,
        "needs_review": 0,
        "export_eligible": 1,
        "rejected": 0,
    }


def test_orphan_test_case_is_rejected():
    result = validate_draft_suite(
        draft_suite_data(test_cases=[draft_test_case_data(requirement_ids=["req_001"], obligation_ids=["obl_999"])]),
        governed_ledger_data(),
        obligation_ledger_data(obligations=[]),
    )

    test_case = result.validated_suite.to_dict()["test_cases"][0]

    assert test_case["status"] == "rejected"
    assert test_case["export_eligible"] is False
    assert "unknown obligation obl_999" in test_case["rejection_reasons"]


def test_unknown_requirement_id_is_rejected():
    result = validate_draft_suite(
        draft_suite_data(test_cases=[draft_test_case_data(requirement_ids=["req_missing"])]),
        governed_ledger_data(),
        obligation_ledger_data(),
    )

    test_case = result.validated_suite.to_dict()["test_cases"][0]

    assert test_case["status"] == "rejected"
    assert test_case["export_eligible"] is False
    assert "unknown requirement req_missing" in test_case["rejection_reasons"]


def test_unknown_obligation_id_is_rejected():
    result = validate_draft_suite(
        draft_suite_data(test_cases=[draft_test_case_data(obligation_ids=["obl_missing"])]),
        governed_ledger_data(),
        obligation_ledger_data(),
    )

    test_case = result.validated_suite.to_dict()["test_cases"][0]

    assert test_case["status"] == "rejected"
    assert test_case["export_eligible"] is False
    assert "unknown obligation obl_missing" in test_case["rejection_reasons"]


def test_conflicting_requirement_makes_test_non_exportable():
    result = validate_draft_suite(
        draft_suite_data(),
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    status="conflicting",
                    conflicts_with=["req_002"],
                ),
                governed_requirement(
                    requirement_id="req_002",
                    statement="The bot may show order status without an order number.",
                    source_refs=[source_ref(chunk_id="chunk_002")],
                    candidate_ids=["cand_002"],
                ),
            ],
            governance_summary={
                "conflicting": 1,
                "duplicate": 0,
                "inferred": 0,
                "needs_clarification": 0,
                "out_of_scope": 0,
                "rejected": 0,
                "validated": 1,
            },
        ),
        obligation_ledger_data(
            obligations=[
                obligation_data(
                    status="blocked_unclear_requirement",
                    obligation_type="blocked_conflict",
                    blocked_reason="Conflicting requirement must be resolved before testing.",
                )
            ]
        ),
    )

    test_case = result.validated_suite.to_dict()["test_cases"][0]

    assert test_case["status"] == "needs_review"
    assert test_case["export_eligible"] is False
    assert "conflicting requirement req_001" in test_case["rejection_reasons"]


def test_missing_source_refs_prevent_valid_and_exportable_statuses():
    result = validate_draft_suite(
        draft_suite_data(test_cases=[draft_test_case_data(source_refs=None)]),
        governed_ledger_data(),
        obligation_ledger_data(),
    )

    test_case = result.validated_suite.to_dict()["test_cases"][0]

    assert test_case["status"] == "needs_review"
    assert test_case["export_eligible"] is False
    assert "missing source_refs" in test_case["rejection_reasons"]


@pytest.mark.parametrize("draft_status", ["valid", "approved", "exported"])
def test_source_less_exportable_statuses_are_schema_invalid_inputs(draft_status):
    with pytest.raises(InvalidTestValidationInputError, match="source_refs"):
        validate_draft_suite(
            draft_suite_data(test_cases=[draft_test_case_data(status=draft_status, source_refs=None)]),
            governed_ledger_data(),
            obligation_ledger_data(),
        )


def test_duplicate_test_case_is_rejected():
    duplicate = draft_test_case_data(test_case_id="tc_002")
    result = validate_draft_suite(
        draft_suite_data(test_cases=[draft_test_case_data(), duplicate]),
        governed_ledger_data(),
        obligation_ledger_data(),
    )

    first, second = result.validated_suite.to_dict()["test_cases"]

    assert first["status"] == "valid"
    assert second["status"] == "rejected"
    assert second["export_eligible"] is False
    assert "duplicate test case content" in second["rejection_reasons"]


def test_artifact_entrypoint_writes_validated_suite_and_coverage_report(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(store)
    write_obligation_ledger(store)
    write_source_package(store)
    draft_artifact = write_draft_suite(store)

    result = validate_tests_from_draft_suite_artifact(draft_artifact.path)

    expected_suite_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "08_validated_tests"
        / "validated_test_suite.json"
    )
    expected_coverage_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "08_validated_tests"
        / "coverage_report.json"
    )
    assert result.validated_suite_path == expected_suite_path
    assert result.coverage_report_path == expected_coverage_path
    assert ValidatedTestSuite.from_dict(json.loads(expected_suite_path.read_text(encoding="utf-8"))) == (
        result.validated_suite
    )
    assert CoverageReport.from_dict(json.loads(expected_coverage_path.read_text(encoding="utf-8"))) == (
        result.coverage_report
    )


def test_missing_governed_ledger_artifact_is_reported(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_obligation_ledger(store)
    draft_artifact = write_draft_suite(store)

    with pytest.raises(InvalidTestValidationInputError, match="GovernedRequirementLedger"):
        validate_tests_from_draft_suite_artifact(draft_artifact.path)

    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "08_validated_tests"
        / "validated_test_suite.json"
    ).exists()


def test_draft_suite_artifact_path_must_match_c12_input_convention(tmp_path):
    invalid_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "wrong"
        / "draft_test_suite.json"
    )

    with pytest.raises(DraftTestSuiteArtifactError, match="07_draft_tests"):
        validate_tests_from_draft_suite_artifact(invalid_path)


def test_golden_fixture_draft_suite_to_validated_suite_and_coverage_report(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(
        store,
        data=json.loads((GOLDEN_DIR / "governed_requirement_ledger.json").read_text(encoding="utf-8")),
    )
    write_obligation_ledger(
        store,
        data=json.loads((GOLDEN_DIR / "test_obligation_ledger.json").read_text(encoding="utf-8")),
    )
    write_source_package(
        store,
        data=json.loads((GOLDEN_DIR / "source_package.json").read_text(encoding="utf-8")),
    )
    draft_artifact = write_draft_suite(
        store,
        data=json.loads((GOLDEN_DIR / "draft_test_suite.json").read_text(encoding="utf-8")),
    )
    expected_suite = json.loads((GOLDEN_DIR / "validated_test_suite.json").read_text(encoding="utf-8"))
    expected_coverage = json.loads((GOLDEN_DIR / "coverage_report.json").read_text(encoding="utf-8"))

    result = validate_tests_from_draft_suite_artifact(draft_artifact.path)

    assert result.validated_suite.to_dict() == expected_suite
    assert result.coverage_report.to_dict() == expected_coverage
    assert stable_json(result.validated_suite.to_dict()) == (
        GOLDEN_DIR / "validated_test_suite.json"
    ).read_text(encoding="utf-8")
    assert stable_json(result.coverage_report.to_dict()) == (
        GOLDEN_DIR / "coverage_report.json"
    ).read_text(encoding="utf-8")


def test_cli_validate_tests_smoke_delegates_to_c12(tmp_path, monkeypatch, capsys):
    draft_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "07_draft_tests"
        / "draft_test_suite.json"
    )
    validated_path = tmp_path / "validated_test_suite.json"
    coverage_path = tmp_path / "coverage_report.json"
    calls = []

    def fake_validate(draft_suite):
        calls.append(draft_suite)
        return SimpleNamespace(
            validated_suite_path=validated_path,
            coverage_report_path=coverage_path,
        )

    monkeypatch.setattr(cli, "validate_tests_from_draft_suite_artifact", fake_validate)

    exit_code = cli.main(["validate-tests", "--draft-suite", str(draft_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(validated_path) in captured.out
    assert str(coverage_path) in captured.out
    assert captured.err == ""
    assert calls == [draft_path]


def test_cli_validate_tests_reports_invalid_input(tmp_path, capsys):
    missing_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "07_draft_tests"
        / "draft_test_suite.json"
    )

    exit_code = cli.main(["validate-tests", "--draft-suite", str(missing_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "error:" in captured.err
    assert "DraftTestSuite" in captured.err


def test_c12_writes_no_future_component_artifacts(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(store)
    write_obligation_ledger(store)
    write_source_package(store)
    draft_artifact = write_draft_suite(store)

    validate_tests_from_draft_suite_artifact(draft_artifact.path)

    files = sorted(path.relative_to(artifact_root).as_posix() for path in artifact_root.rglob("*") if path.is_file())
    assert files == [
        "demo_chatbot/run_001/02_source_package/source_package.json",
        "demo_chatbot/run_001/05_governed_requirements/governed_requirement_ledger.json",
        "demo_chatbot/run_001/06_test_obligations/test_obligation_ledger.json",
        "demo_chatbot/run_001/07_draft_tests/draft_test_suite.json",
        "demo_chatbot/run_001/08_validated_tests/coverage_report.json",
        "demo_chatbot/run_001/08_validated_tests/validated_test_suite.json",
    ]


def test_c12_implementation_has_no_future_component_skill_or_provider_dependencies():
    source = inspect.getsource(test_validation)

    for forbidden in (
        "SkillRuntime",
        "SkillDefinition",
        "ExecutorExportPackage",
        "ReviewReport",
        "op" + "enai",
        "anth" + "ropic",
        "lang" + "chain",
        "llama" + "_index",
        "req" + "uests",
        "ht" + "tpx",
        "url" + "lib",
        "so" + "cket",
        "sub" + "process",
    ):
        assert forbidden not in source
