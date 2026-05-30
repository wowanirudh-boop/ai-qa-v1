import hashlib
from pathlib import Path

import pytest

from ai_testgen.artifact_store import (
    ArtifactExistsError,
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactStore,
    ArtifactTypeError,
    MalformedArtifactError,
)
from ai_testgen.schemas import SchemaValidationError, SourceChunk


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "artifact_store"


def source_chunk_data(**overrides: object) -> dict:
    data = {
        "chunk_id": "chunk_001",
        "document_id": "doc_001",
        "text": "The bot must ask for an order number.",
        "checksum": "sha256:def456",
        "processing_status": "not_processed",
    }
    data.update(overrides)
    return data


def test_write_and_read_json_artifact_round_trip(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    artifact = source_chunk_data()

    written = store.write_json(
        project_id="demo_chatbot",
        run_id="run_001",
        stage="02_source_package",
        artifact_name="source_chunk",
        artifact=artifact,
    )

    assert written.path == (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "02_source_package"
        / "source_chunk.json"
    )
    assert store.read_json("demo_chatbot", "run_001", "02_source_package", "source_chunk") == artifact


def test_stable_json_serialization_matches_golden_fixture(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    artifact = {
        "zeta": 3,
        "nested": {"b": False, "a": True},
        "items": [{"z": "last", "a": "first"}],
    }

    written = store.write_json("demo_chatbot", "run_001", "02_source_package", "stable", artifact)

    assert written.path.read_text(encoding="utf-8") == (
        GOLDEN_DIR / "stable_artifact.json"
    ).read_text(encoding="utf-8")


def test_checksum_is_generated_from_persisted_bytes(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    written = store.write_json(
        "demo_chatbot",
        "run_001",
        "02_source_package",
        "source_chunk",
        source_chunk_data(),
    )
    expected = f"sha256:{hashlib.sha256(written.path.read_bytes()).hexdigest()}"

    assert written.checksum == expected
    assert store.checksum("demo_chatbot", "run_001", "02_source_package", "source_chunk") == expected


def test_artifact_existence_checks_and_missing_artifact_behavior(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")

    assert store.exists("demo_chatbot", "run_001", "02_source_package", "missing") is False

    with pytest.raises(ArtifactNotFoundError, match="missing"):
        store.read_json("demo_chatbot", "run_001", "02_source_package", "missing")

    with pytest.raises(ArtifactNotFoundError, match="missing"):
        store.checksum("demo_chatbot", "run_001", "02_source_package", "missing")


def test_malformed_json_is_rejected(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    path = store.artifact_path("demo_chatbot", "run_001", "02_source_package", "bad")
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(MalformedArtifactError, match="Malformed JSON"):
        store.read_json("demo_chatbot", "run_001", "02_source_package", "bad")


@pytest.mark.parametrize(
    ("project_id", "run_id", "stage", "artifact_name"),
    [
        ("../demo_chatbot", "run_001", "02_source_package", "source_chunk"),
        ("demo_chatbot", "..\\run_001", "02_source_package", "source_chunk"),
        ("demo_chatbot", "run_001", "../02_source_package", "source_chunk"),
        ("demo_chatbot", "run_001", "02_source_package", "../source_chunk"),
        ("demo_chatbot", "run_001", "02_source_package", "source_chunk.json"),
    ],
)
def test_invalid_paths_and_path_traversal_are_rejected(
    tmp_path, project_id, run_id, stage, artifact_name
):
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactPathError):
        store.artifact_path(project_id, run_id, stage, artifact_name)


def test_repeated_writes_create_new_versions_instead_of_overwriting(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    first = source_chunk_data(text="First version.")
    second = source_chunk_data(text="Second version.")

    first_written = store.write_json("demo_chatbot", "run_001", "02_source_package", "source_chunk", first)
    second_written = store.write_json(
        "demo_chatbot",
        "run_001",
        "02_source_package",
        "source_chunk",
        second,
    )

    assert first_written.path.name == "source_chunk.json"
    assert second_written.path.name == "source_chunk.v2.json"
    assert store.read_json("demo_chatbot", "run_001", "02_source_package", "source_chunk") == first
    assert store.read_json("demo_chatbot", "run_001", "02_source_package", "source_chunk", version=2) == second


def test_explicit_existing_version_cannot_be_overwritten(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")

    store.write_json("demo_chatbot", "run_001", "02_source_package", "source_chunk", source_chunk_data())

    with pytest.raises(ArtifactExistsError, match="source_chunk.json"):
        store.write_json(
            "demo_chatbot",
            "run_001",
            "02_source_package",
            "source_chunk",
            source_chunk_data(text="Attempted overwrite."),
            version=1,
        )


def test_schema_model_objects_can_be_written_and_loaded(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    chunk = SourceChunk.from_dict(source_chunk_data())

    store.write_json("demo_chatbot", "run_001", "02_source_package", "source_chunk", chunk)

    assert store.load_model(
        SourceChunk,
        "demo_chatbot",
        "run_001",
        "02_source_package",
        "source_chunk",
    ) == chunk


def test_schema_loading_rejects_invalid_contract_data(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    store.write_json(
        "demo_chatbot",
        "run_001",
        "02_source_package",
        "source_chunk",
        source_chunk_data(processing_status="processed"),
    )

    with pytest.raises(SchemaValidationError, match="processing_status"):
        store.load_model(SourceChunk, "demo_chatbot", "run_001", "02_source_package", "source_chunk")


def test_unexpected_artifact_types_are_rejected(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactTypeError, match="mapping"):
        store.write_json("demo_chatbot", "run_001", "02_source_package", "items", ["not", "an", "object"])

    store.write_json("demo_chatbot", "run_001", "02_source_package", "source_chunk", source_chunk_data())

    with pytest.raises(ArtifactTypeError, match="SchemaModel"):
        store.load_model(dict, "demo_chatbot", "run_001", "02_source_package", "source_chunk")
