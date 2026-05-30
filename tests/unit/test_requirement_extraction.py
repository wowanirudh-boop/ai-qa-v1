import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_testgen.cli as cli
import ai_testgen.requirement_extraction as requirement_extraction
from ai_testgen.artifact_store import ArtifactStore
from ai_testgen.requirement_extraction import (
    InvalidRequirementExtractionSkillError,
    InvalidCandidateRequirementPackageError,
    RequirementExtractionError,
    SourcePackageArtifactError,
    extract_requirements_from_source_package_artifact,
)
from ai_testgen.schemas import CandidateRequirementPackage, SkillDefinition, SkillRunRecord, SourcePackage
from ai_testgen.skill_runtime import SkillRuntime


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "requirement_extraction"


def source_ref(chunk_id: str = "chunk_001", document_id: str = "doc_001") -> dict:
    return {"document_id": document_id, "chunk_id": chunk_id}


def source_chunk(
    *,
    chunk_id: str = "chunk_001",
    text: str = "The bot must ask for an order number.",
    status: str = "not_processed",
) -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": "doc_001",
        "text": text,
        "checksum": f"sha256:{chunk_id}",
        "processing_status": status,
    }


def source_package_data(**overrides: object) -> dict:
    data = {
        "source_package_id": "source_pkg_001",
        "project_id": "demo_chatbot",
        "document_ids": ["doc_001"],
        "chunks": [
            source_chunk(),
            source_chunk(chunk_id="chunk_002", text="Company background context."),
        ],
        "checksum": "sha256:pkg001",
    }
    data.update(overrides)
    return data


def candidate_requirement(**overrides: object) -> dict:
    data = {
        "candidate_id": "cand_001",
        "statement": "The bot must ask for an order number before helping with order status.",
        "requirement_type_guess": "functional",
        "source_refs": [source_ref()],
        "confidence": 0.91,
    }
    data.update(overrides)
    return data


def second_candidate_requirement(**overrides: object) -> dict:
    data = {
        "candidate_id": "skill_candidate_99",
        "statement": "The bot must explain company background context.",
        "requirement_type_guess": "functional",
        "source_refs": [source_ref(chunk_id="chunk_002")],
        "confidence": 0.8,
    }
    data.update(overrides)
    return data


def candidate_package_data(**overrides: object) -> dict:
    data = {
        "candidate_package_id": "cand_pkg_001",
        "project_id": "demo_chatbot",
        "source_package_id": "source_pkg_001",
        "candidates": [candidate_requirement()],
    }
    data.update(overrides)
    return data


def requirement_extraction_skill_definition(**overrides: object) -> SkillDefinition:
    data = {
        "skill_id": "fake_requirement_extraction_v1",
        "name": "Fake Requirement Extraction",
        "version": "1.0.0",
        "input_contract": "SourcePackage",
        "output_contract": "CandidateRequirementPackage",
        "entrypoint": "tests.fake_requirement_extraction",
    }
    data.update(overrides)
    return SkillDefinition.from_dict(data)


def stable_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


class FakeRequirementExtractionAdapter:
    def __init__(self, output: dict) -> None:
        self.output = output
        self.calls = []

    def execute(self, skill_definition, input_artifacts):
        self.calls.append((skill_definition, input_artifacts))
        return self.output


def write_source_package(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "02_source_package",
        "source_package",
        data or source_package_data(),
    )


def runtime_with_adapter(artifact_root: Path, output: dict) -> tuple[SkillRuntime, FakeRequirementExtractionAdapter]:
    adapter = FakeRequirementExtractionAdapter(output)
    return SkillRuntime(artifact_root=artifact_root, adapter=adapter), adapter


def test_extract_requirements_happy_path_invokes_skill_runtime_and_writes_artifacts(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    source_artifact = write_source_package(store)
    runtime, adapter = runtime_with_adapter(artifact_root, candidate_package_data())

    result = extract_requirements_from_source_package_artifact(
        source_artifact.path,
        requirement_extraction_skill_definition(),
        skill_runtime=runtime,
    )

    expected_candidate_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "candidate_requirement_package.json"
    )
    assert result.candidate_package_path == expected_candidate_path
    assert result.candidate_package.to_dict() == candidate_package_data()
    assert CandidateRequirementPackage.from_dict(
        json.loads(expected_candidate_path.read_text(encoding="utf-8"))
    ) == result.candidate_package
    assert result.skill_run_record.status == "succeeded"
    assert result.skill_run_record.skill_run_id == "skill_run_001"
    assert len(adapter.calls) == 1
    assert isinstance(adapter.calls[0][1][0], SourcePackage)

    status_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "source_package_extraction_status.json"
    )
    assert result.source_status_path == status_path
    updated_source = SourcePackage.from_dict(json.loads(status_path.read_text(encoding="utf-8")))
    assert [chunk.processing_status for chunk in updated_source.chunks] == [
        "requirements_extracted",
        "not_processed",
    ]

    original_source = SourcePackage.from_dict(json.loads(source_artifact.path.read_text(encoding="utf-8")))
    for original_chunk, updated_chunk in zip(original_source.chunks, updated_source.chunks):
        assert updated_chunk.chunk_id == original_chunk.chunk_id
        assert updated_chunk.document_id == original_chunk.document_id
        assert updated_chunk.text == original_chunk.text
        assert updated_chunk.checksum == original_chunk.checksum
    assert [chunk.processing_status for chunk in original_source.chunks] == ["not_processed", "not_processed"]

    run_record_path = artifact_root / "demo_chatbot" / "run_001" / "skill_runs" / "skill_run_001.json"
    assert SkillRunRecord.from_dict(json.loads(run_record_path.read_text(encoding="utf-8"))) == (
        result.skill_run_record
    )


def test_candidate_missing_source_refs_is_rejected_by_schema_validation(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    source_artifact = write_source_package(store)
    invalid_output = candidate_package_data(candidates=[candidate_requirement(source_refs=[])])
    runtime, _adapter = runtime_with_adapter(artifact_root, invalid_output)

    with pytest.raises(RequirementExtractionError, match="source_refs"):
        extract_requirements_from_source_package_artifact(
            source_artifact.path,
            requirement_extraction_skill_definition(),
            skill_runtime=runtime,
        )

    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "candidate_requirement_package.json"
    ).exists()


def test_unknown_chunk_reference_fails_cross_artifact_validation(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    source_artifact = write_source_package(store)
    invalid_output = candidate_package_data(
        candidates=[candidate_requirement(source_refs=[source_ref(chunk_id="chunk_missing")])]
    )
    runtime, _adapter = runtime_with_adapter(artifact_root, invalid_output)

    with pytest.raises(InvalidCandidateRequirementPackageError, match="unknown source chunk"):
        extract_requirements_from_source_package_artifact(
            source_artifact.path,
            requirement_extraction_skill_definition(),
            skill_runtime=runtime,
        )

    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "source_package_extraction_status.json"
    ).exists()
    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "candidate_requirement_package.json"
    ).exists()


def test_candidate_confidence_outside_range_is_rejected_by_schema_validation(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    source_artifact = write_source_package(store)
    invalid_output = candidate_package_data(candidates=[candidate_requirement(confidence=1.01)])
    runtime, _adapter = runtime_with_adapter(artifact_root, invalid_output)

    with pytest.raises(RequirementExtractionError, match="confidence"):
        extract_requirements_from_source_package_artifact(
            source_artifact.path,
            requirement_extraction_skill_definition(),
            skill_runtime=runtime,
        )

    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "candidate_requirement_package.json"
    ).exists()


def test_c07_assigns_deterministic_candidate_package_and_candidate_ids(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    source_artifact = write_source_package(store)
    skill_output = candidate_package_data(
        candidate_package_id="skill_owned_package_id",
        candidates=[
            candidate_requirement(candidate_id="skill_candidate_a"),
            second_candidate_requirement(),
        ],
    )
    runtime, _adapter = runtime_with_adapter(artifact_root, skill_output)

    result = extract_requirements_from_source_package_artifact(
        source_artifact.path,
        requirement_extraction_skill_definition(),
        skill_runtime=runtime,
    )

    assert result.candidate_package.candidate_package_id == "cand_pkg_001"
    assert [candidate.candidate_id for candidate in result.candidate_package.candidates] == [
        "cand_001",
        "cand_002",
    ]
    assert CandidateRequirementPackage.from_dict(
        json.loads(result.candidate_package_path.read_text(encoding="utf-8"))
    ) == result.candidate_package


def test_only_not_processed_chunks_are_sent_to_requirement_extraction_skill(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    source_artifact = write_source_package(
        store,
        data=source_package_data(
            chunks=[
                source_chunk(),
                source_chunk(
                    chunk_id="chunk_002",
                    text="Already extracted.",
                    status="requirements_extracted",
                ),
            ]
        ),
    )
    runtime, adapter = runtime_with_adapter(artifact_root, candidate_package_data())

    result = extract_requirements_from_source_package_artifact(
        source_artifact.path,
        requirement_extraction_skill_definition(),
        skill_runtime=runtime,
    )

    skill_input = adapter.calls[0][1][0]
    assert [chunk.chunk_id for chunk in skill_input.chunks] == ["chunk_001"]
    updated_source = SourcePackage.from_dict(json.loads(result.source_status_path.read_text(encoding="utf-8")))
    assert [chunk.processing_status for chunk in updated_source.chunks] == [
        "requirements_extracted",
        "requirements_extracted",
    ]


def test_no_eligible_chunks_fails_before_skill_runtime_execution(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    source_artifact = write_source_package(
        store,
        data=source_package_data(
            chunks=[
                source_chunk(status="requirements_extracted"),
                source_chunk(chunk_id="chunk_002", text="Out of scope.", status="out_of_scope"),
            ]
        ),
    )
    runtime, adapter = runtime_with_adapter(artifact_root, candidate_package_data())

    with pytest.raises(SourcePackageArtifactError, match="eligible"):
        extract_requirements_from_source_package_artifact(
            source_artifact.path,
            requirement_extraction_skill_definition(),
            skill_runtime=runtime,
        )

    assert adapter.calls == []
    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "candidate_requirement_package.json"
    ).exists()


def test_requirement_extraction_skill_must_declare_c07_contracts(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    source_artifact = write_source_package(store)
    runtime, adapter = runtime_with_adapter(artifact_root, candidate_package_data())

    with pytest.raises(InvalidRequirementExtractionSkillError, match="input_contract"):
        extract_requirements_from_source_package_artifact(
            source_artifact.path,
            requirement_extraction_skill_definition(input_contract="ProjectConfig"),
            skill_runtime=runtime,
        )

    with pytest.raises(InvalidRequirementExtractionSkillError, match="output_contract"):
        extract_requirements_from_source_package_artifact(
            source_artifact.path,
            requirement_extraction_skill_definition(output_contract="SourcePackage"),
            skill_runtime=runtime,
        )

    assert adapter.calls == []


def test_updated_source_package_status_artifact_uses_artifact_store_versioning(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    source_artifact = write_source_package(store)
    store.write_json(
        "demo_chatbot",
        "run_001",
        "03_candidate_requirements",
        "source_package_extraction_status",
        source_package_data(),
    )
    runtime, _adapter = runtime_with_adapter(artifact_root, candidate_package_data())

    result = extract_requirements_from_source_package_artifact(
        source_artifact.path,
        requirement_extraction_skill_definition(),
        skill_runtime=runtime,
    )

    assert result.source_status_path.name == "source_package_extraction_status.v2.json"
    assert source_artifact.path.name == "source_package.json"
    original_source = SourcePackage.from_dict(json.loads(source_artifact.path.read_text(encoding="utf-8")))
    assert [chunk.processing_status for chunk in original_source.chunks] == ["not_processed", "not_processed"]


def test_golden_fixture_source_package_to_candidate_package(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    source_data = json.loads((GOLDEN_DIR / "source_package.json").read_text(encoding="utf-8"))
    expected_candidate = json.loads(
        (GOLDEN_DIR / "candidate_requirement_package.json").read_text(encoding="utf-8")
    )
    source_artifact = write_source_package(store, data=source_data)
    runtime, _adapter = runtime_with_adapter(artifact_root, expected_candidate)

    result = extract_requirements_from_source_package_artifact(
        source_artifact.path,
        requirement_extraction_skill_definition(),
        skill_runtime=runtime,
    )

    assert stable_json(result.candidate_package.to_dict()) == (
        GOLDEN_DIR / "candidate_requirement_package.json"
    ).read_text(encoding="utf-8")


def test_cli_extract_requirements_smoke_delegates_to_c07(tmp_path, monkeypatch, capsys):
    source_path = tmp_path / "artifacts" / "demo_chatbot" / "run_001" / "02_source_package" / "source_package.json"
    skill_definition_path = tmp_path / "skills" / "requirement_extraction_v1.json"
    candidate_path = tmp_path / "candidate_requirement_package.json"
    calls = []

    def fake_extract(source_package, skill_definition):
        calls.append((source_package, skill_definition))
        return SimpleNamespace(candidate_package_path=candidate_path)

    monkeypatch.setattr(cli, "extract_requirements_from_source_package_artifact", fake_extract)

    exit_code = cli.main(
        [
            "extract-requirements",
            "--source-package",
            str(source_path),
            "--skill-definition",
            str(skill_definition_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(candidate_path) in captured.out
    assert captured.err == ""
    assert calls == [(source_path, skill_definition_path)]


def test_cli_extract_requirements_reports_missing_skill_definition(tmp_path, capsys):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    source_artifact = write_source_package(store)
    missing_skill = tmp_path / "skills" / "missing.json"

    exit_code = cli.main(
        [
            "extract-requirements",
            "--source-package",
            str(source_artifact.path),
            "--skill-definition",
            str(missing_skill),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "error:" in captured.err
    assert "SkillDefinition" in captured.err


def test_c07_writes_no_future_component_artifacts(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    source_artifact = write_source_package(store)
    runtime, _adapter = runtime_with_adapter(artifact_root, candidate_package_data())

    extract_requirements_from_source_package_artifact(
        source_artifact.path,
        requirement_extraction_skill_definition(),
        skill_runtime=runtime,
    )

    files = sorted(path.relative_to(artifact_root).as_posix() for path in artifact_root.rglob("*") if path.is_file())
    assert files == [
        "demo_chatbot/run_001/02_source_package/source_package.json",
        "demo_chatbot/run_001/03_candidate_requirements/candidate_requirement_package.json",
        "demo_chatbot/run_001/03_candidate_requirements/candidate_requirement_package_skill_output.json",
        "demo_chatbot/run_001/03_candidate_requirements/source_package_extraction_input.json",
        "demo_chatbot/run_001/03_candidate_requirements/source_package_extraction_status.json",
        "demo_chatbot/run_001/skill_runs/skill_run_001.json",
    ]


def test_c07_implementation_has_no_future_component_or_provider_dependencies():
    source = inspect.getsource(requirement_extraction)

    for forbidden in (
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
