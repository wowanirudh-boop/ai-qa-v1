import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_testgen.cli as cli
from ai_testgen.artifact_store import ArtifactStore
from ai_testgen.schemas import ExecutorExportPackage


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "executor_export"


def source_ref(chunk_id: str = "chunk_001", document_id: str = "doc_001") -> dict:
    return {"document_id": document_id, "chunk_id": chunk_id}


def project_config_data(**overrides: object) -> dict:
    data = {
        "project_id": "demo_chatbot",
        "bot_name": "Demo Support Bot",
        "target_url": "https://example.test/chat",
        "coverage_policy": {"require_positive_tests": True},
        "approval_policy": {"allow_export_without_review": False},
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


def validated_test_case_data(**overrides: object) -> dict:
    data = {
        "test_case_id": "tc_001",
        "title": "Order status requires order number",
        "status": "valid",
        "requirement_ids": ["req_001"],
        "obligation_ids": ["obl_001"],
        "source_refs": [source_ref()],
        "turns": [conversation_turn()],
        "assertions": [assertion()],
        "priority": "p1",
        "tags": ["order_status"],
        "export_eligible": True,
    }
    data.update(overrides)
    return data


def validated_suite_data(**overrides: object) -> dict:
    data = {
        "validated_suite_id": "validated_suite_001",
        "project_id": "demo_chatbot",
        "draft_suite_id": "draft_suite_001",
        "test_cases": [validated_test_case_data()],
        "validation_summary": {
            "valid": 1,
            "needs_review": 0,
            "rejected": 0,
            "export_eligible": 1,
        },
    }
    data.update(overrides)
    return data


def ineligible_test_case() -> dict:
    return validated_test_case_data(
        test_case_id="tc_002",
        title="Rejected test is not exported",
        status="rejected",
        export_eligible=False,
        rejection_reasons=["unknown obligation obl_missing"],
        obligation_ids=["obl_missing"],
    )


def stable_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_project_config(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "00_project_config",
        "project_config",
        data or project_config_data(),
    )


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


def write_validated_suite(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "08_validated_tests",
        "validated_test_suite",
        data or validated_suite_data(),
    )


def test_eligible_tests_are_exported_to_executor_json():
    from ai_testgen.executor_export import build_executor_export

    result = build_executor_export(
        validated_suite_data(test_cases=[validated_test_case_data(), ineligible_test_case()]),
        governed_ledger_data(),
        obligation_ledger_data(),
        project_config_data(),
        run_id="run_001",
    )

    assert result.executor_tests == json.loads((GOLDEN_DIR / "tests.json").read_text(encoding="utf-8"))
    assert result.export_package.to_dict() == json.loads(
        (GOLDEN_DIR / "executor_export_package.json").read_text(encoding="utf-8")
    )


def test_unknown_requirement_link_prevents_export():
    from ai_testgen.executor_export import build_executor_export

    result = build_executor_export(
        validated_suite_data(
            test_cases=[validated_test_case_data(requirement_ids=["req_missing"])]
        ),
        governed_ledger_data(),
        obligation_ledger_data(),
        project_config_data(),
        run_id="run_001",
    )

    assert result.executor_tests["tests"] == []
    assert result.export_package.exported_test_case_ids == []
    assert result.export_package.eligibility_summary == {"eligible": 0, "excluded": 1}


def test_unknown_obligation_link_prevents_export_for_otherwise_exportable_test():
    from ai_testgen.executor_export import build_executor_export

    result = build_executor_export(
        validated_suite_data(
            test_cases=[validated_test_case_data(obligation_ids=["obl_missing"])]
        ),
        governed_ledger_data(),
        obligation_ledger_data(),
        project_config_data(),
        run_id="run_001",
    )

    assert result.executor_tests["tests"] == []
    assert result.export_package.exported_test_case_ids == []
    assert result.export_package.eligibility_summary == {"eligible": 0, "excluded": 1}


def test_rejected_requirement_link_prevents_export():
    from ai_testgen.executor_export import build_executor_export

    result = build_executor_export(
        validated_suite_data(),
        governed_ledger_data(
            requirements=[governed_requirement(status="rejected", rationale="Rejected by reviewer.")],
            governance_summary={"validated": 0, "rejected": 1},
        ),
        obligation_ledger_data(),
        project_config_data(),
        run_id="run_001",
    )

    assert result.executor_tests["tests"] == []
    assert result.export_package.eligibility_summary == {"eligible": 0, "excluded": 1}


def test_conflicting_requirement_link_prevents_export():
    from ai_testgen.executor_export import build_executor_export

    result = build_executor_export(
        validated_suite_data(),
        governed_ledger_data(
            requirements=[governed_requirement(status="conflicting", conflicts_with=["req_002"])],
            governance_summary={"validated": 0, "conflicting": 1},
        ),
        obligation_ledger_data(
            obligations=[
                obligation_data(
                    status="blocked_unclear_requirement",
                    obligation_type="blocked_conflict",
                    blocked_reason="Conflict must be resolved first.",
                )
            ]
        ),
        project_config_data(),
        run_id="run_001",
    )

    assert result.executor_tests["tests"] == []
    assert result.export_package.eligibility_summary == {"eligible": 0, "excluded": 1}


def test_non_normal_obligation_status_prevents_export():
    from ai_testgen.executor_export import build_executor_export

    result = build_executor_export(
        validated_suite_data(),
        governed_ledger_data(),
        obligation_ledger_data(
            obligations=[
                obligation_data(
                    status="skipped_by_policy",
                    obligation_type="skipped_by_policy",
                )
            ]
        ),
        project_config_data(),
        run_id="run_001",
    )

    assert result.executor_tests["tests"] == []
    assert result.export_package.exported_test_case_ids == []
    assert result.export_package.eligibility_summary == {"eligible": 0, "excluded": 1}


def test_missing_source_refs_prevents_export():
    from ai_testgen.executor_export import build_executor_export

    result = build_executor_export(
        validated_suite_data(
            test_cases=[
                validated_test_case_data(
                    status="needs_review",
                    source_refs=None,
                    export_eligible=False,
                    rejection_reasons=["missing source_refs"],
                )
            ]
        ),
        governed_ledger_data(),
        obligation_ledger_data(),
        project_config_data(),
        run_id="run_001",
    )

    assert result.executor_tests["tests"] == []
    assert result.export_package.eligibility_summary == {"eligible": 0, "excluded": 1}


def test_source_ref_mismatch_prevents_export():
    from ai_testgen.executor_export import build_executor_export

    result = build_executor_export(
        validated_suite_data(
            test_cases=[
                validated_test_case_data(
                    source_refs=[source_ref(chunk_id="chunk_002")],
                )
            ]
        ),
        governed_ledger_data(),
        obligation_ledger_data(),
        project_config_data(),
        run_id="run_001",
    )

    assert result.executor_tests["tests"] == []
    assert result.export_package.exported_test_case_ids == []
    assert result.export_package.eligibility_summary == {"eligible": 0, "excluded": 1}


def test_artifact_entrypoint_writes_tests_and_export_package(tmp_path):
    from ai_testgen.executor_export import export_tests_from_validated_suite_artifact

    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    inputs = [
        write_project_config(store),
        write_governed_ledger(store),
        write_obligation_ledger(store),
        write_validated_suite(
            store,
            data=validated_suite_data(test_cases=[validated_test_case_data(), ineligible_test_case()]),
        ),
    ]
    original_input_bytes = {artifact.path: artifact.path.read_bytes() for artifact in inputs}

    result = export_tests_from_validated_suite_artifact(inputs[3].path)

    expected_tests_path = artifact_root / "demo_chatbot" / "run_001" / "10_executor_export" / "tests.json"
    expected_package_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "10_executor_export"
        / "executor_export_package.json"
    )
    assert result.tests_path == expected_tests_path
    assert result.export_package_path == expected_package_path
    assert expected_tests_path.read_text(encoding="utf-8") == (GOLDEN_DIR / "tests.json").read_text(
        encoding="utf-8"
    )
    package = json.loads(expected_package_path.read_text(encoding="utf-8"))
    assert ExecutorExportPackage.from_dict(package) == result.export_package
    assert package == json.loads((GOLDEN_DIR / "executor_export_package.json").read_text(encoding="utf-8"))
    for path, original_bytes in original_input_bytes.items():
        assert path.read_bytes() == original_bytes


def test_missing_project_config_artifact_is_reported_before_outputs(tmp_path):
    from ai_testgen.executor_export import InvalidExecutorExportInputError
    from ai_testgen.executor_export import export_tests_from_validated_suite_artifact

    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(store)
    write_obligation_ledger(store)
    validated = write_validated_suite(store)

    with pytest.raises(InvalidExecutorExportInputError, match="ProjectConfig"):
        export_tests_from_validated_suite_artifact(validated.path)

    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "10_executor_export"
        / "tests.json"
    ).exists()


def test_validated_suite_artifact_path_must_match_c14_input_convention(tmp_path):
    from ai_testgen.executor_export import ValidatedSuiteArtifactError
    from ai_testgen.executor_export import export_tests_from_validated_suite_artifact

    invalid_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "wrong"
        / "validated_test_suite.json"
    )

    with pytest.raises(ValidatedSuiteArtifactError, match="08_validated_tests"):
        export_tests_from_validated_suite_artifact(invalid_path)


def test_c14_writes_no_future_component_artifacts(tmp_path):
    from ai_testgen.executor_export import export_tests_from_validated_suite_artifact

    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_project_config(store)
    write_governed_ledger(store)
    write_obligation_ledger(store)
    validated = write_validated_suite(store)

    export_tests_from_validated_suite_artifact(validated.path)

    files = sorted(path.relative_to(artifact_root).as_posix() for path in artifact_root.rglob("*") if path.is_file())
    assert files == [
        "demo_chatbot/run_001/00_project_config/project_config.json",
        "demo_chatbot/run_001/05_governed_requirements/governed_requirement_ledger.json",
        "demo_chatbot/run_001/06_test_obligations/test_obligation_ledger.json",
        "demo_chatbot/run_001/08_validated_tests/validated_test_suite.json",
        "demo_chatbot/run_001/10_executor_export/executor_export_package.json",
        "demo_chatbot/run_001/10_executor_export/tests.json",
    ]


def test_cli_export_smoke_delegates_to_c14(tmp_path, monkeypatch, capsys):
    validated_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "08_validated_tests"
        / "validated_test_suite.json"
    )
    tests_path = tmp_path / "tests.json"
    package_path = tmp_path / "executor_export_package.json"
    calls = []

    def fake_export(validated_suite):
        calls.append(validated_suite)
        return SimpleNamespace(tests_path=tests_path, export_package_path=package_path)

    monkeypatch.setattr(cli, "export_tests_from_validated_suite_artifact", fake_export)

    exit_code = cli.main(["export", "--validated-suite", str(validated_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(tests_path) in captured.out
    assert str(package_path) in captured.out
    assert captured.err == ""
    assert calls == [validated_path]


def test_c14_implementation_has_no_runtime_skill_or_executor_execution_dependencies():
    import ai_testgen.executor_export as executor_export

    source = inspect.getsource(executor_export)

    for forbidden in (
        "SkillRuntime",
        "SkillDefinition",
        "run_skill",
        "ReviewReport",
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
