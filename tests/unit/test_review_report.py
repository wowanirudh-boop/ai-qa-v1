import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_testgen.cli as cli
from ai_testgen.artifact_store import ArtifactStore
from ai_testgen.schemas import ReviewReportMetadata


GOLDEN_C12_DIR = Path(__file__).parent / "fixtures" / "golden" / "test_validation_coverage"
GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "review_report"


def load_golden_c12(name: str) -> dict:
    return json.loads((GOLDEN_C12_DIR / name).read_text(encoding="utf-8"))


def write_governed_ledger(store: ArtifactStore):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "05_governed_requirements",
        "governed_requirement_ledger",
        load_golden_c12("governed_requirement_ledger.json"),
    )


def write_obligation_ledger(store: ArtifactStore):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "06_test_obligations",
        "test_obligation_ledger",
        load_golden_c12("test_obligation_ledger.json"),
    )


def write_validated_suite(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "08_validated_tests",
        "validated_test_suite",
        data or load_golden_c12("validated_test_suite.json"),
    )


def write_coverage_report(store: ArtifactStore):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "08_validated_tests",
        "coverage_report",
        load_golden_c12("coverage_report.json"),
    )


def write_c13_inputs(store: ArtifactStore):
    governed = write_governed_ledger(store)
    obligations = write_obligation_ledger(store)
    validated = write_validated_suite(store)
    coverage = write_coverage_report(store)
    return governed, obligations, validated, coverage


def stable_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def test_review_report_artifact_entrypoint_writes_report_and_metadata(tmp_path):
    from ai_testgen.review_report import generate_review_report_from_validated_suite_artifact

    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    inputs = write_c13_inputs(store)
    original_input_bytes = {artifact.path: artifact.path.read_bytes() for artifact in inputs}

    result = generate_review_report_from_validated_suite_artifact(inputs[2].path)

    expected_report_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "09_review_report"
        / "review_report.md"
    )
    expected_metadata_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "09_review_report"
        / "review_report_metadata.json"
    )
    assert result.report_path == expected_report_path
    assert result.metadata_path == expected_metadata_path
    assert expected_report_path.read_text(encoding="utf-8") == (
        GOLDEN_DIR / "review_report.md"
    ).read_text(encoding="utf-8")

    metadata = json.loads(expected_metadata_path.read_text(encoding="utf-8"))
    assert ReviewReportMetadata.from_dict(metadata) == result.metadata
    assert metadata == {
        "coverage_report_id": "coverage_001",
        "governed_ledger_id": "gov_ledger_001",
        "obligation_ledger_id": "obl_ledger_001",
        "project_id": "demo_chatbot",
        "report_path": "artifacts/demo_chatbot/run_001/09_review_report/review_report.md",
        "review_report_id": "review_001",
        "summary": {
            "approval_needed_requirements": 0,
            "blocked_obligations": 0,
            "non_exportable_tests": 4,
            "rejected_tests": 0,
            "uncovered_obligations": 0,
            "uncovered_requirements": 0,
        },
        "validated_suite_id": "validated_suite_001",
    }
    for path, original_bytes in original_input_bytes.items():
        assert path.read_bytes() == original_bytes


def test_report_includes_coverage_summary_rejected_and_blocked_items(tmp_path):
    from ai_testgen.review_report import generate_review_report_from_validated_suite_artifact

    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    _, _, validated, _ = write_c13_inputs(store)

    result = generate_review_report_from_validated_suite_artifact(validated.path)
    report = result.report_path.read_text(encoding="utf-8")

    assert "| skipped | 1 |" in report
    assert "## Blocked Obligations\n\n- None" in report
    assert "tc_002 (needs_review, export_eligible=False): Unsupported order ID self-service tracking." in report
    assert "tc_003 (needs_review, export_eligible=False): Raw API response shown as chatbot output." in report


def test_missing_coverage_report_artifact_is_reported(tmp_path):
    from ai_testgen.review_report import InvalidReviewReportInputError
    from ai_testgen.review_report import generate_review_report_from_validated_suite_artifact

    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(store)
    write_obligation_ledger(store)
    validated = write_validated_suite(store)

    with pytest.raises(InvalidReviewReportInputError, match="CoverageReport"):
        generate_review_report_from_validated_suite_artifact(validated.path)

    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "09_review_report"
        / "review_report.md"
    ).exists()


def test_malformed_governed_ledger_artifact_is_rejected_before_outputs(tmp_path):
    from ai_testgen.review_report import InvalidReviewReportInputError
    from ai_testgen.review_report import generate_review_report_from_validated_suite_artifact

    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    governed_data = load_golden_c12("governed_requirement_ledger.json")
    governed_data["requirements"][0]["status"] = "ready_for_review"
    store.write_json(
        "demo_chatbot",
        "run_001",
        "05_governed_requirements",
        "governed_requirement_ledger",
        governed_data,
    )
    write_obligation_ledger(store)
    validated = write_validated_suite(store)
    write_coverage_report(store)

    with pytest.raises(InvalidReviewReportInputError, match="GovernedRequirementLedger"):
        generate_review_report_from_validated_suite_artifact(validated.path)

    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "09_review_report"
        / "review_report.md"
    ).exists()


def test_review_report_input_path_must_match_c13_input_convention(tmp_path):
    from ai_testgen.review_report import ValidatedSuiteArtifactError
    from ai_testgen.review_report import generate_review_report_from_validated_suite_artifact

    invalid_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "wrong"
        / "validated_test_suite.json"
    )

    with pytest.raises(ValidatedSuiteArtifactError, match="08_validated_tests"):
        generate_review_report_from_validated_suite_artifact(invalid_path)


def test_review_report_rejects_mismatched_artifact_ids(tmp_path):
    from ai_testgen.review_report import InvalidReviewReportInputError
    from ai_testgen.review_report import generate_review_report_from_validated_suite_artifact

    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(store)
    write_obligation_ledger(store)
    validated_data = load_golden_c12("validated_test_suite.json")
    validated_data["validated_suite_id"] = "validated_suite_other"
    validated = write_validated_suite(store, data=validated_data)
    write_coverage_report(store)

    with pytest.raises(InvalidReviewReportInputError, match="validated_suite_id"):
        generate_review_report_from_validated_suite_artifact(validated.path)


def test_cli_review_report_smoke_delegates_to_c13(tmp_path, monkeypatch, capsys):
    validated_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "08_validated_tests"
        / "validated_test_suite.json"
    )
    report_path = tmp_path / "review_report.md"
    metadata_path = tmp_path / "review_report_metadata.json"
    calls = []

    def fake_generate(validated_suite):
        calls.append(validated_suite)
        return SimpleNamespace(report_path=report_path, metadata_path=metadata_path)

    monkeypatch.setattr(cli, "generate_review_report_from_validated_suite_artifact", fake_generate)

    exit_code = cli.main(["review-report", "--validated-suite", str(validated_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(report_path) in captured.out
    assert str(metadata_path) in captured.out
    assert captured.err == ""
    assert calls == [validated_path]


def test_cli_review_report_reports_invalid_input(tmp_path, capsys):
    missing_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "08_validated_tests"
        / "validated_test_suite.json"
    )

    exit_code = cli.main(["review-report", "--validated-suite", str(missing_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "error:" in captured.err
    assert "ValidatedTestSuite" in captured.err


def test_c13_writes_no_future_component_artifacts(tmp_path):
    from ai_testgen.review_report import generate_review_report_from_validated_suite_artifact

    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    _, _, validated, _ = write_c13_inputs(store)

    generate_review_report_from_validated_suite_artifact(validated.path)

    files = sorted(path.relative_to(artifact_root).as_posix() for path in artifact_root.rglob("*") if path.is_file())
    assert files == [
        "demo_chatbot/run_001/05_governed_requirements/governed_requirement_ledger.json",
        "demo_chatbot/run_001/06_test_obligations/test_obligation_ledger.json",
        "demo_chatbot/run_001/08_validated_tests/coverage_report.json",
        "demo_chatbot/run_001/08_validated_tests/validated_test_suite.json",
        "demo_chatbot/run_001/09_review_report/review_report.md",
        "demo_chatbot/run_001/09_review_report/review_report_metadata.json",
    ]


def test_c13_implementation_has_no_runtime_skill_or_export_dependencies():
    import ai_testgen.review_report as review_report

    source = inspect.getsource(review_report)

    for forbidden in (
        "SkillRuntime",
        "SkillDefinition",
        "run_skill",
        "ExecutorExportPackage",
        "openai",
        "anthropic",
        "google.generativeai",
        "lang" + "chain",
        "llama" + "_index",
        "requests",
        "httpx",
        "urllib",
        "socket",
        "subprocess",
    ):
        assert forbidden not in source
