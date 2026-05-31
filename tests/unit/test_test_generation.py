import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_testgen.cli as cli
import ai_testgen.test_generation as test_generation
from ai_testgen.artifact_store import ArtifactStore
from ai_testgen.schemas import DraftTestSuite, GovernedRequirementLedger, SkillDefinition, SkillRunRecord
from ai_testgen.schemas import TestObligationLedger as SchemaTestObligationLedger
from ai_testgen.skill_runtime import SkillRuntime
from ai_testgen.test_generation import (
    DEFAULT_TEST_CASE_WRITER_SKILL_DEFINITION_PATH,
    InvalidDraftTestSuiteError,
    InvalidTestGenerationSkillError,
    TestGenerationError as C11TestGenerationError,
    generate_tests_from_obligation_ledger_artifact,
)


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "test_generation"


def source_ref(chunk_id: str = "chunk_001", document_id: str = "doc_001") -> dict:
    return {"document_id": document_id, "chunk_id": chunk_id}


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
        "description": "Verify order status is not provided before an order number is collected.",
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
        "turn_id": "skill_turn",
        "speaker": "user",
        "text": "Where is my order?",
        "expected_intent": "check_order_status",
    }
    data.update(overrides)
    return data


def assertion(**overrides: object) -> dict:
    data = {
        "assertion_id": "skill_assert",
        "assertion_type": "bot_response_contains_request",
        "target": "bot.final_response",
        "expected": "The bot asks for the order number before providing status.",
    }
    data.update(overrides)
    return data


def draft_test_case_data(**overrides: object) -> dict:
    data = {
        "test_case_id": "skill_tc",
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
        "draft_suite_id": "skill_draft_suite",
        "project_id": "demo_chatbot",
        "obligation_ledger_id": "obl_ledger_001",
        "test_cases": [draft_test_case_data()],
    }
    data.update(overrides)
    return data


def expected_draft_suite_data(**overrides: object) -> dict:
    data = {
        "draft_suite_id": "draft_suite_001",
        "project_id": "demo_chatbot",
        "obligation_ledger_id": "obl_ledger_001",
        "test_cases": [
            draft_test_case_data(
                test_case_id="tc_001",
                turns=[conversation_turn(turn_id="turn_001")],
                assertions=[assertion(assertion_id="assert_001")],
            )
        ],
        "skill_run_ids": ["skill_run_001", "skill_run_002"],
    }
    data.update(overrides)
    return data


def writer_skill_definition(**overrides: object) -> SkillDefinition:
    data = {
        "skill_id": "fake_test_case_writer_v1",
        "name": "Fake Test Case Writer",
        "version": "1.0.0",
        "input_contract": "TestObligationLedger",
        "output_contract": "DraftTestSuite",
        "entrypoint": "tests.fake_test_case_writer",
    }
    data.update(overrides)
    return SkillDefinition.from_dict(data)


def oracle_generator_skill_definition(**overrides: object) -> SkillDefinition:
    data = {
        "skill_id": "fake_oracle_generator_v1",
        "name": "Fake Oracle Generator",
        "version": "1.0.0",
        "input_contract": "DraftTestSuite",
        "output_contract": "DraftTestSuite",
        "entrypoint": "tests.fake_oracle_generator",
    }
    data.update(overrides)
    return SkillDefinition.from_dict(data)


def stable_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


class FakeTestGenerationAdapter:
    def __init__(self, writer_output: dict, oracle_output: dict | None = None) -> None:
        self.writer_output = writer_output
        self.oracle_output = oracle_output
        self.calls = []

    def execute(self, skill_definition, input_artifacts):
        self.calls.append((skill_definition, input_artifacts))
        if skill_definition.output_contract != "DraftTestSuite":
            raise AssertionError("C11 should only ask skills for DraftTestSuite output")
        if skill_definition.skill_id.endswith("oracle_generator_v1"):
            if self.oracle_output is not None:
                return self.oracle_output
            output = input_artifacts[0].to_dict()
            output["test_cases"][0]["assertions"] = [assertion()]
            return output
        return self.writer_output


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


def runtime_with_adapter(
    artifact_root: Path,
    writer_output: dict,
    oracle_output: dict | None = None,
) -> tuple[SkillRuntime, FakeTestGenerationAdapter]:
    adapter = FakeTestGenerationAdapter(writer_output, oracle_output)
    return SkillRuntime(artifact_root=artifact_root, adapter=adapter), adapter


def write_skill_definition(path: Path, definition: SkillDefinition) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(definition.to_dict()), encoding="utf-8")
    return path


def test_generate_tests_happy_path_invokes_skill_runtime_and_writes_artifacts(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(store)
    obligation_artifact = write_obligation_ledger(store)
    writer_output = draft_suite_data(test_cases=[draft_test_case_data(assertions=[])])
    runtime, adapter = runtime_with_adapter(artifact_root, writer_output)

    result = generate_tests_from_obligation_ledger_artifact(
        obligation_artifact.path,
        writer_skill_definition(),
        oracle_generator_skill_definition(),
        skill_runtime=runtime,
    )

    expected_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "07_draft_tests"
        / "draft_test_suite.json"
    )
    assert result.draft_suite_path == expected_path
    assert result.draft_suite.to_dict() == expected_draft_suite_data()
    assert DraftTestSuite.from_dict(json.loads(expected_path.read_text(encoding="utf-8"))) == result.draft_suite
    assert [record.status for record in result.skill_run_records] == ["succeeded", "succeeded"]
    assert [record.skill_run_id for record in result.skill_run_records] == ["skill_run_001", "skill_run_002"]

    assert len(adapter.calls) == 2
    assert isinstance(adapter.calls[0][1][0], SchemaTestObligationLedger)
    assert isinstance(adapter.calls[1][1][0], DraftTestSuite)
    skill_input = adapter.calls[0][1][0]
    assert [obligation.obligation_id for obligation in skill_input.obligations] == ["obl_001"]
    assert skill_input.metadata == {"linked_requirements": [governed_requirement()]}

    run_record_path = artifact_root / "demo_chatbot" / "run_001" / "skill_runs" / "skill_run_001.json"
    assert SkillRunRecord.from_dict(json.loads(run_record_path.read_text(encoding="utf-8"))) == (
        result.skill_run_records[0]
    )


def test_missing_requirement_ids_from_skill_output_fails(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(store)
    obligation_artifact = write_obligation_ledger(store)
    writer_output = draft_suite_data(test_cases=[draft_test_case_data(requirement_ids=[])])
    runtime, _adapter = runtime_with_adapter(artifact_root, writer_output)

    with pytest.raises(C11TestGenerationError, match="requirement_ids"):
        generate_tests_from_obligation_ledger_artifact(
            obligation_artifact.path,
            writer_skill_definition(),
            oracle_generator_skill_definition(),
            skill_runtime=runtime,
        )

    assert not (
        artifact_root / "demo_chatbot" / "run_001" / "07_draft_tests" / "draft_test_suite.json"
    ).exists()


def test_missing_obligation_ids_from_skill_output_fails(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(store)
    obligation_artifact = write_obligation_ledger(store)
    writer_output = draft_suite_data(test_cases=[draft_test_case_data(obligation_ids=[])])
    runtime, _adapter = runtime_with_adapter(artifact_root, writer_output)

    with pytest.raises(C11TestGenerationError, match="obligation_ids"):
        generate_tests_from_obligation_ledger_artifact(
            obligation_artifact.path,
            writer_skill_definition(),
            oracle_generator_skill_definition(),
            skill_runtime=runtime,
        )

    assert not (
        artifact_root / "demo_chatbot" / "run_001" / "07_draft_tests" / "draft_test_suite.json"
    ).exists()


def test_unknown_obligation_reference_from_skill_output_fails(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(store)
    obligation_artifact = write_obligation_ledger(store)
    writer_output = draft_suite_data(test_cases=[draft_test_case_data(obligation_ids=["obl_missing"])])
    runtime, _adapter = runtime_with_adapter(artifact_root, writer_output)

    with pytest.raises(InvalidDraftTestSuiteError, match="unknown obligation"):
        generate_tests_from_obligation_ledger_artifact(
            obligation_artifact.path,
            writer_skill_definition(),
            oracle_generator_skill_definition(),
            skill_runtime=runtime,
        )

    assert not (
        artifact_root / "demo_chatbot" / "run_001" / "07_draft_tests" / "draft_test_suite.json"
    ).exists()


def test_draft_test_source_refs_must_match_linked_obligations(tmp_path):
    refs = [
        {"document_id": "doc_001", "chunk_id": "chunk_001", "location": "requirements.md:1"},
        {"document_id": "doc_002", "chunk_id": "chunk_009"},
    ]
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(store, data=governed_ledger_data(requirements=[governed_requirement(source_refs=refs)]))
    obligation_artifact = write_obligation_ledger(store, data=obligation_ledger_data(obligations=[obligation_data(source_refs=refs)]))
    writer_output = draft_suite_data(test_cases=[draft_test_case_data(source_refs=[source_ref()])])
    runtime, _adapter = runtime_with_adapter(artifact_root, writer_output)

    with pytest.raises(InvalidDraftTestSuiteError, match="source_refs"):
        generate_tests_from_obligation_ledger_artifact(
            obligation_artifact.path,
            writer_skill_definition(),
            oracle_generator_skill_definition(),
            skill_runtime=runtime,
        )


def test_requirement_ids_must_match_linked_obligation_requirements(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(
        store,
        data=governed_ledger_data(
            requirements=[
                governed_requirement(),
                governed_requirement(
                    requirement_id="req_002",
                    statement="The bot must explain refund timing.",
                    source_refs=[source_ref(chunk_id="chunk_002")],
                    candidate_ids=["cand_002"],
                ),
            ]
        ),
    )
    obligation_artifact = write_obligation_ledger(store)
    writer_output = draft_suite_data(test_cases=[draft_test_case_data(requirement_ids=["req_002"])])
    runtime, _adapter = runtime_with_adapter(artifact_root, writer_output)

    with pytest.raises(InvalidDraftTestSuiteError, match="requirement_ids"):
        generate_tests_from_obligation_ledger_artifact(
            obligation_artifact.path,
            writer_skill_definition(),
            oracle_generator_skill_definition(),
            skill_runtime=runtime,
        )


def test_test_generation_skill_must_declare_c11_contracts(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(store)
    obligation_artifact = write_obligation_ledger(store)
    runtime, adapter = runtime_with_adapter(artifact_root, draft_suite_data())

    with pytest.raises(InvalidTestGenerationSkillError, match="input_contract"):
        generate_tests_from_obligation_ledger_artifact(
            obligation_artifact.path,
            writer_skill_definition(input_contract="SourcePackage"),
            oracle_generator_skill_definition(),
            skill_runtime=runtime,
        )

    with pytest.raises(InvalidTestGenerationSkillError, match="output_contract"):
        generate_tests_from_obligation_ledger_artifact(
            obligation_artifact.path,
            writer_skill_definition(output_contract="ValidatedTestSuite"),
            oracle_generator_skill_definition(),
            skill_runtime=runtime,
        )

    assert adapter.calls == []


def test_missing_default_skill_definition_fails_without_test_generation(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(store)
    obligation_artifact = write_obligation_ledger(store)
    runtime, adapter = runtime_with_adapter(artifact_root, draft_suite_data())
    monkeypatch.setattr(
        test_generation,
        "DEFAULT_TEST_CASE_WRITER_SKILL_DEFINITION_PATH",
        tmp_path / "skills" / "missing_test_case_writer_v1.json",
    )

    with pytest.raises(InvalidTestGenerationSkillError, match="SkillDefinition file not found"):
        generate_tests_from_obligation_ledger_artifact(
            obligation_artifact.path,
            skill_runtime=runtime,
        )

    assert adapter.calls == []
    assert not (
        artifact_root / "demo_chatbot" / "run_001" / "07_draft_tests" / "draft_test_suite.json"
    ).exists()


def test_golden_fixture_obligation_ledger_to_draft_suite(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    governed_ledger = json.loads((GOLDEN_DIR / "governed_requirement_ledger.json").read_text(encoding="utf-8"))
    obligation_ledger = json.loads((GOLDEN_DIR / "test_obligation_ledger.json").read_text(encoding="utf-8"))
    expected_draft_suite = json.loads((GOLDEN_DIR / "draft_test_suite.json").read_text(encoding="utf-8"))
    write_governed_ledger(store, data=governed_ledger)
    obligation_artifact = write_obligation_ledger(store, data=obligation_ledger)
    writer_output = draft_suite_data(test_cases=[draft_test_case_data(assertions=[])])
    runtime, _adapter = runtime_with_adapter(artifact_root, writer_output)

    result = generate_tests_from_obligation_ledger_artifact(
        obligation_artifact.path,
        writer_skill_definition(),
        oracle_generator_skill_definition(),
        skill_runtime=runtime,
    )

    assert result.draft_suite.to_dict() == expected_draft_suite
    assert stable_json(result.draft_suite.to_dict()) == (
        GOLDEN_DIR / "draft_test_suite.json"
    ).read_text(encoding="utf-8")


def test_cli_generate_tests_smoke_delegates_to_c11(tmp_path, monkeypatch, capsys):
    obligations_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "06_test_obligations"
        / "test_obligation_ledger.json"
    )
    writer_skill_definition_path = tmp_path / "skills" / "test_case_writer_v1.json"
    oracle_skill_definition_path = tmp_path / "skills" / "oracle_generator_v1.json"
    draft_path = tmp_path / "draft_test_suite.json"
    calls = []

    def fake_generate_tests(obligations, test_case_writer_skill_definition=None, oracle_generator_skill_definition=None):
        calls.append((obligations, test_case_writer_skill_definition, oracle_generator_skill_definition))
        return SimpleNamespace(draft_suite_path=draft_path)

    monkeypatch.setattr(cli, "generate_tests_from_obligation_ledger_artifact", fake_generate_tests)

    exit_code = cli.main(
        [
            "generate-tests",
            "--obligations",
            str(obligations_path),
            "--skill-definition",
            str(writer_skill_definition_path),
            "--oracle-skill-definition",
            str(oracle_skill_definition_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(draft_path) in captured.out
    assert captured.err == ""
    assert calls == [(obligations_path, writer_skill_definition_path, oracle_skill_definition_path)]


def test_cli_generate_tests_reports_invalid_input(tmp_path, capsys):
    missing_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "06_test_obligations"
        / "test_obligation_ledger.json"
    )

    exit_code = cli.main(["generate-tests", "--obligations", str(missing_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "error:" in captured.err
    assert "TestObligationLedger" in captured.err


def test_c11_writes_no_future_component_artifacts(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_governed_ledger(store)
    obligation_artifact = write_obligation_ledger(store)
    writer_output = draft_suite_data(test_cases=[draft_test_case_data(assertions=[])])
    runtime, _adapter = runtime_with_adapter(artifact_root, writer_output)

    generate_tests_from_obligation_ledger_artifact(
        obligation_artifact.path,
        writer_skill_definition(),
        oracle_generator_skill_definition(),
        skill_runtime=runtime,
    )

    files = sorted(path.relative_to(artifact_root).as_posix() for path in artifact_root.rglob("*") if path.is_file())
    assert files == [
        "demo_chatbot/run_001/05_governed_requirements/governed_requirement_ledger.json",
        "demo_chatbot/run_001/06_test_obligations/test_obligation_ledger.json",
        "demo_chatbot/run_001/07_draft_tests/draft_test_suite.json",
        "demo_chatbot/run_001/07_draft_tests/draft_test_suite_oracle_output.json",
        "demo_chatbot/run_001/07_draft_tests/draft_test_suite_skill_output.json",
        "demo_chatbot/run_001/07_draft_tests/test_generation_input.json",
        "demo_chatbot/run_001/skill_runs/skill_run_001.json",
        "demo_chatbot/run_001/skill_runs/skill_run_002.json",
    ]


def test_c11_implementation_has_no_future_component_raw_document_or_provider_dependencies():
    source = inspect.getsource(test_generation)

    for forbidden in (
        "SourcePackage",
        "SourceChunk",
        "CandidateRequirementPackage",
        "AtomicRequirementLedger",
        "ValidatedTestSuite",
        "CoverageReport",
        "ExecutorExportPackage",
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


def test_default_c11_skill_definition_path_points_to_test_case_writer():
    assert DEFAULT_TEST_CASE_WRITER_SKILL_DEFINITION_PATH.as_posix() == "skills/test_case_writer_v1.json"
