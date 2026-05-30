import inspect
import json
from pathlib import Path

import pytest

import ai_testgen.skill_runtime as skill_runtime
from ai_testgen.artifact_store import ArtifactStore
from ai_testgen.schemas import CandidateRequirementPackage, SkillRunRecord, SourcePackage
from ai_testgen.schemas import SkillDefinition
from ai_testgen.skill_runtime import (
    InvalidSkillDefinitionError,
    SkillExecutionError,
    SkillRuntime,
    load_skill_definition,
)


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "skill_runtime"


def source_ref() -> dict:
    return {"document_id": "doc_001", "chunk_id": "chunk_001"}


def source_chunk() -> dict:
    return {
        "chunk_id": "chunk_001",
        "document_id": "doc_001",
        "text": "The bot must ask for an order number.",
        "checksum": "sha256:def456",
        "processing_status": "not_processed",
    }


def source_package_data(**overrides: object) -> dict:
    data = {
        "source_package_id": "source_pkg_001",
        "project_id": "demo_chatbot",
        "document_ids": ["doc_001"],
        "chunks": [source_chunk()],
        "checksum": "sha256:pkg001",
    }
    data.update(overrides)
    return data


def candidate_requirement() -> dict:
    return {
        "candidate_id": "cand_001",
        "statement": "The bot must ask for an order number before helping with order status.",
        "requirement_type_guess": "functional",
        "source_refs": [source_ref()],
        "confidence": 0.91,
    }


def candidate_package_data(**overrides: object) -> dict:
    data = {
        "candidate_package_id": "cand_pkg_001",
        "project_id": "demo_chatbot",
        "source_package_id": "source_pkg_001",
        "candidates": [candidate_requirement()],
    }
    data.update(overrides)
    return data


def stable_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


class FakeSkillAdapter:
    def __init__(self, output: dict | Exception) -> None:
        self.output = output
        self.calls = []

    def execute(self, skill_definition, input_artifacts):
        self.calls.append((skill_definition, input_artifacts))
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


def write_source_package(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "02_source_package",
        "source_package",
        data or source_package_data(),
    )


def test_valid_skill_definition_loads_from_golden_fixture():
    definition = load_skill_definition(GOLDEN_DIR / "fake_skill_definition.json")

    assert definition.to_dict() == {
        "skill_id": "fake_requirement_extraction_v1",
        "name": "Fake Requirement Extraction",
        "version": "1.0.0",
        "input_contract": "SourcePackage",
        "output_contract": "CandidateRequirementPackage",
        "entrypoint": "tests.fake_requirement_extraction",
    }


def test_invalid_skill_definition_fails_for_missing_or_unknown_contract(tmp_path):
    missing_contract = {
        "skill_id": "fake_requirement_extraction_v1",
        "name": "Fake Requirement Extraction",
        "version": "1.0.0",
        "input_contract": "SourcePackage",
        "entrypoint": "tests.fake_requirement_extraction",
    }
    missing_path = tmp_path / "missing_contract.json"
    missing_path.write_text(stable_json(missing_contract), encoding="utf-8")

    with pytest.raises(InvalidSkillDefinitionError, match="output_contract"):
        load_skill_definition(missing_path)

    unknown_contract = dict(missing_contract, output_contract="ImaginaryContract")
    unknown_path = tmp_path / "unknown_contract.json"
    unknown_path.write_text(stable_json(unknown_contract), encoding="utf-8")

    with pytest.raises(InvalidSkillDefinitionError, match="ImaginaryContract"):
        load_skill_definition(unknown_path)


def test_fake_skill_execution_validates_io_writes_output_and_records_success(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    input_artifact = write_source_package(store)
    output_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "candidate_requirement_package.json"
    )
    definition = load_skill_definition(GOLDEN_DIR / "fake_skill_definition.json")
    adapter = FakeSkillAdapter(candidate_package_data())
    runtime = SkillRuntime(artifact_root=artifact_root, adapter=adapter)

    record = runtime.run_skill(
        definition,
        input_artifact_paths=[input_artifact.path],
        output_artifact_paths=[output_path],
        skill_run_id="skill_run_001",
    )

    expected_record = json.loads((GOLDEN_DIR / "succeeded_skill_run_record.json").read_text(encoding="utf-8"))
    assert record.to_dict() == expected_record
    assert len(adapter.calls) == 1
    assert isinstance(adapter.calls[0][1][0], SourcePackage)
    assert CandidateRequirementPackage.from_dict(json.loads(output_path.read_text(encoding="utf-8")))
    assert output_path.read_text(encoding="utf-8") == (
        GOLDEN_DIR / "candidate_requirement_package.json"
    ).read_text(encoding="utf-8")
    run_record_path = artifact_root / "demo_chatbot" / "run_001" / "skill_runs" / "skill_run_001.json"
    assert SkillRunRecord.from_dict(json.loads(run_record_path.read_text(encoding="utf-8"))) == record
    assert run_record_path.read_text(encoding="utf-8") == stable_json(expected_record)


def test_existing_skill_run_record_fails_before_adapter_or_output_write(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    input_artifact = write_source_package(store)
    store.write_json(
        "demo_chatbot",
        "run_001",
        "skill_runs",
        "skill_run_001",
        {
            "skill_run_id": "skill_run_001",
            "skill_id": "fake_requirement_extraction_v1",
            "status": "succeeded",
            "input_artifact_paths": [
                "artifacts/demo_chatbot/run_001/02_source_package/source_package.json"
            ],
            "output_artifact_paths": [
                "artifacts/demo_chatbot/run_001/03_candidate_requirements/candidate_requirement_package.json"
            ],
        },
    )
    output_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "candidate_requirement_package.json"
    )
    definition = load_skill_definition(GOLDEN_DIR / "fake_skill_definition.json")
    adapter = FakeSkillAdapter(candidate_package_data())
    runtime = SkillRuntime(artifact_root=artifact_root, adapter=adapter)

    with pytest.raises(SkillExecutionError, match="skill_run_001"):
        runtime.run_skill(
            definition,
            input_artifact_paths=[input_artifact.path],
            output_artifact_paths=[output_path],
            skill_run_id="skill_run_001",
        )

    assert adapter.calls == []
    assert not output_path.exists()


def test_failed_fake_skill_records_error_without_writing_output(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    input_artifact = write_source_package(store)
    output_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "candidate_requirement_package.json"
    )
    definition = load_skill_definition(GOLDEN_DIR / "fake_skill_definition.json")
    runtime = SkillRuntime(artifact_root=artifact_root, adapter=FakeSkillAdapter(RuntimeError("fake failure")))

    with pytest.raises(SkillExecutionError, match="fake failure"):
        runtime.run_skill(
            definition,
            input_artifact_paths=[input_artifact.path],
            output_artifact_paths=[output_path],
            skill_run_id="skill_run_001",
        )

    assert not output_path.exists()
    run_record_path = artifact_root / "demo_chatbot" / "run_001" / "skill_runs" / "skill_run_001.json"
    record = SkillRunRecord.from_dict(json.loads(run_record_path.read_text(encoding="utf-8")))
    assert record.status == "failed"
    assert "fake failure" in record.error
    assert record.input_artifact_paths == [
        "artifacts/demo_chatbot/run_001/02_source_package/source_package.json"
    ]
    assert record.output_artifact_paths == [
        "artifacts/demo_chatbot/run_001/03_candidate_requirements/candidate_requirement_package.json"
    ]


def test_run_skill_records_unknown_contract_failure_when_artifact_context_is_valid(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    input_artifact = write_source_package(store)
    output_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "candidate_requirement_package.json"
    )
    definition = SkillDefinition.from_dict(
        {
            "skill_id": "fake_requirement_extraction_v1",
            "name": "Fake Requirement Extraction",
            "version": "1.0.0",
            "input_contract": "SourcePackage",
            "output_contract": "ImaginaryContract",
            "entrypoint": "tests.fake_requirement_extraction",
        }
    )
    adapter = FakeSkillAdapter(candidate_package_data())
    runtime = SkillRuntime(artifact_root=artifact_root, adapter=adapter)

    with pytest.raises(SkillExecutionError, match="ImaginaryContract"):
        runtime.run_skill(
            definition,
            input_artifact_paths=[input_artifact.path],
            output_artifact_paths=[output_path],
            skill_run_id="skill_run_001",
        )

    assert adapter.calls == []
    assert not output_path.exists()
    record = SkillRunRecord.from_dict(
        json.loads((artifact_root / "demo_chatbot" / "run_001" / "skill_runs" / "skill_run_001.json").read_text())
    )
    assert record.status == "failed"
    assert "ImaginaryContract" in record.error


def test_input_contract_validation_happens_before_skill_execution(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    bad_input = source_package_data(chunks=[source_chunk() | {"processing_status": "processed"}])
    input_artifact = write_source_package(store, data=bad_input)
    output_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "candidate_requirement_package.json"
    )
    definition = load_skill_definition(GOLDEN_DIR / "fake_skill_definition.json")
    adapter = FakeSkillAdapter(candidate_package_data())
    runtime = SkillRuntime(artifact_root=artifact_root, adapter=adapter)

    with pytest.raises(SkillExecutionError, match="processing_status"):
        runtime.run_skill(
            definition,
            input_artifact_paths=[input_artifact.path],
            output_artifact_paths=[output_path],
            skill_run_id="skill_run_001",
        )

    assert adapter.calls == []
    assert not output_path.exists()
    record = SkillRunRecord.from_dict(
        json.loads((artifact_root / "demo_chatbot" / "run_001" / "skill_runs" / "skill_run_001.json").read_text())
    )
    assert record.status == "failed"
    assert "processing_status" in record.error


def test_output_contract_validation_happens_before_output_is_persisted(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    input_artifact = write_source_package(store)
    output_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "candidate_requirement_package.json"
    )
    invalid_output = candidate_package_data(candidates=[candidate_requirement() | {"source_refs": []}])
    definition = load_skill_definition(GOLDEN_DIR / "fake_skill_definition.json")
    runtime = SkillRuntime(artifact_root=artifact_root, adapter=FakeSkillAdapter(invalid_output))

    with pytest.raises(SkillExecutionError, match="source_refs"):
        runtime.run_skill(
            definition,
            input_artifact_paths=[input_artifact.path],
            output_artifact_paths=[output_path],
            skill_run_id="skill_run_001",
        )

    assert not output_path.exists()
    record = SkillRunRecord.from_dict(
        json.loads((artifact_root / "demo_chatbot" / "run_001" / "skill_runs" / "skill_run_001.json").read_text())
    )
    assert record.status == "failed"
    assert "source_refs" in record.error


def test_c06_implementation_has_no_provider_specific_or_future_component_logic():
    source = inspect.getsource(skill_runtime)

    for forbidden in (
        "CandidateRequirement",
        "AtomicRequirement",
        "TestObligation",
        "DraftTestSuite",
        "TestCase",
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
