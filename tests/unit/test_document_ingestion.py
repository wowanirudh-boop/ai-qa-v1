import hashlib
import inspect
import json
from pathlib import Path

import pytest

import ai_testgen.document_ingestion as document_ingestion
from ai_testgen.cli import main
from ai_testgen.document_ingestion import (
    DocumentDecodingError,
    EmptyDocumentError,
    MissingSourcePathError,
    SourcePathIsDirectoryError,
    UnsupportedDocumentTypeError,
    create_document_collection,
    create_document_records,
    ingest_document_file,
    ingest_documents,
)
from ai_testgen.project_config import save_project_config, validate_project_config
from ai_testgen.schemas import Document


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "document_ingestion"


def valid_config_data(**overrides: object) -> dict:
    data = {
        "project_id": "demo_chatbot",
        "bot_name": "Demo Support Bot",
        "target_url": "https://example.test/chat",
        "coverage_policy": {
            "require_negative_tests": True,
            "require_positive_tests": True,
        },
        "approval_policy": {
            "allow_export_without_review": False,
            "require_human_approval_for_inferred": True,
        },
    }
    data.update(overrides)
    return data


def write_text_document(path: Path, content: str = "The bot must ask for an order number.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def content_checksum(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def test_ingest_valid_text_document_creates_valid_document_record(tmp_path):
    source_path = tmp_path / "docs" / "requirements.md"
    write_text_document(source_path)
    config = validate_project_config(
        valid_config_data(
            source_paths=["docs/requirements.md"],
            artifact_root=str(tmp_path / "artifacts"),
        )
    )

    documents = create_document_records(config, source_base_dir=tmp_path)

    assert len(documents) == 1
    document = documents[0]
    assert isinstance(document, Document)
    assert document.to_dict() == {
        "document_id": "doc_001",
        "project_id": "demo_chatbot",
        "source_path": "docs/requirements.md",
        "title": "Requirements",
        "content_checksum": content_checksum(source_path),
        "ingestion_status": "loaded",
        "content_type": "text/markdown",
        "size_bytes": source_path.stat().st_size,
        "metadata": {"encoding": "utf-8"},
    }


def test_document_checksums_are_deterministic_for_same_content(tmp_path):
    first = tmp_path / "docs" / "first.txt"
    second = tmp_path / "docs" / "second.txt"
    write_text_document(first, "Same source text.\n")
    write_text_document(second, "Same source text.\n")

    first_document = ingest_document_file(first, "demo_chatbot", source_base_dir=tmp_path, document_id="doc_001")
    second_document = ingest_document_file(second, "demo_chatbot", source_base_dir=tmp_path, document_id="doc_002")

    assert first_document.content_checksum == second_document.content_checksum
    assert first_document.content_checksum == content_checksum(first)


def test_missing_source_path_fails_clearly(tmp_path):
    config = validate_project_config(
        valid_config_data(
            source_paths=["docs/missing.md"],
            artifact_root=str(tmp_path / "artifacts"),
        )
    )

    with pytest.raises(MissingSourcePathError, match="Source path not found"):
        create_document_records(config, source_base_dir=tmp_path)


def test_directory_passed_as_single_document_fails_clearly(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    with pytest.raises(SourcePathIsDirectoryError, match="Expected a source document file"):
        ingest_document_file(docs_dir, "demo_chatbot", source_base_dir=tmp_path, document_id="doc_001")


def test_unsupported_file_type_fails_clearly(tmp_path):
    unsupported = tmp_path / "docs" / "requirements.pdf"
    write_text_document(unsupported)
    config = validate_project_config(
        valid_config_data(
            source_paths=["docs/requirements.pdf"],
            artifact_root=str(tmp_path / "artifacts"),
        )
    )

    with pytest.raises(UnsupportedDocumentTypeError, match="Unsupported source document type"):
        create_document_records(config, source_base_dir=tmp_path)


def test_invalid_utf8_source_document_fails_clearly(tmp_path):
    invalid = tmp_path / "docs" / "invalid.txt"
    invalid.parent.mkdir(parents=True, exist_ok=True)
    invalid.write_bytes(b"\xff\xfe\xff")
    config = validate_project_config(
        valid_config_data(
            source_paths=["docs/invalid.txt"],
            artifact_root=str(tmp_path / "artifacts"),
        )
    )

    with pytest.raises(DocumentDecodingError, match="UTF-8"):
        create_document_records(config, source_base_dir=tmp_path)


def test_empty_source_document_fails_clearly(tmp_path):
    empty = tmp_path / "docs" / "empty.txt"
    write_text_document(empty, "  \n\t")
    config = validate_project_config(
        valid_config_data(
            source_paths=["docs/empty.txt"],
            artifact_root=str(tmp_path / "artifacts"),
        )
    )

    with pytest.raises(EmptyDocumentError, match="Source document is empty"):
        create_document_records(config, source_base_dir=tmp_path)


def test_project_config_directory_source_paths_are_discovered_deterministically(tmp_path):
    write_text_document(tmp_path / "docs" / "b_policy.md", "Policy text.\n")
    write_text_document(tmp_path / "docs" / "a_requirements.txt", "Requirement text.\n")
    config = validate_project_config(
        valid_config_data(
            source_paths=["docs"],
            artifact_root=str(tmp_path / "artifacts"),
        )
    )

    documents = create_document_records(config, source_base_dir=tmp_path)

    assert [document.document_id for document in documents] == ["doc_001", "doc_002"]
    assert [document.source_path for document in documents] == [
        "docs/a_requirements.txt",
        "docs/b_policy.md",
    ]
    assert [document.content_type for document in documents] == ["text/plain", "text/markdown"]


def test_directory_discovery_ignores_unsupported_non_document_files(tmp_path):
    write_text_document(tmp_path / "docs" / "requirements.md")
    (tmp_path / "docs" / ".gitkeep").write_text("", encoding="utf-8")
    config = validate_project_config(
        valid_config_data(
            source_paths=["docs"],
            artifact_root=str(tmp_path / "artifacts"),
        )
    )

    documents = create_document_records(config, source_base_dir=tmp_path)

    assert [document.source_path for document in documents] == ["docs/requirements.md"]


def test_duplicate_source_paths_do_not_create_duplicate_documents(tmp_path):
    source_path = tmp_path / "docs" / "requirements.md"
    write_text_document(source_path)
    config = validate_project_config(
        valid_config_data(
            source_paths=["docs/requirements.md", str(source_path)],
            artifact_root=str(tmp_path / "artifacts"),
        )
    )

    documents = create_document_records(config, source_base_dir=tmp_path)

    assert [document.source_path for document in documents] == ["docs/requirements.md"]


def test_document_collection_serialization_matches_golden_fixture():
    config = validate_project_config(
        valid_config_data(
            source_paths=[str(GOLDEN_DIR / "requirements.md")],
            artifact_root=str(GOLDEN_DIR / "artifacts"),
        )
    )

    collection = create_document_collection(config, source_base_dir=GOLDEN_DIR)

    assert json.dumps(collection, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n" == (
        GOLDEN_DIR / "documents.json"
    ).read_text(encoding="utf-8")


def test_ingest_documents_persists_only_c04_document_artifact(tmp_path):
    write_text_document(tmp_path / "docs" / "requirements.md")
    artifact_root = tmp_path / "artifacts"
    config = validate_project_config(
        valid_config_data(
            source_paths=["docs/requirements.md"],
            artifact_root=str(artifact_root),
        )
    )

    written = ingest_documents(config, run_id="run_001", source_base_dir=tmp_path)

    assert written.path == artifact_root / "demo_chatbot" / "run_001" / "01_documents" / "documents.json"
    artifact = json.loads(written.path.read_text(encoding="utf-8"))
    assert artifact == create_document_collection(config, source_base_dir=tmp_path)
    files = sorted(path.relative_to(artifact_root).as_posix() for path in artifact_root.rglob("*") if path.is_file())
    assert files == ["demo_chatbot/run_001/01_documents/documents.json"]


def test_cli_ingest_documents_reads_project_config_artifact_and_writes_documents(tmp_path, capsys):
    write_text_document(tmp_path / "docs" / "requirements.md")
    artifact_root = tmp_path / "artifacts"
    config = validate_project_config(
        valid_config_data(
            source_paths=[str(tmp_path / "docs" / "requirements.md")],
            artifact_root=str(artifact_root),
        )
    )
    config_artifact = save_project_config(config, run_id="run_001")

    exit_code = main(["ingest-documents", "--config", str(config_artifact.path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "documents.json" in captured.out
    assert captured.err == ""
    assert (artifact_root / "demo_chatbot" / "run_001" / "01_documents" / "documents.json").exists()


def test_c04_implementation_has_no_future_component_or_model_dependencies():
    source = inspect.getsource(document_ingestion)

    for forbidden in (
        "SourceChunk",
        "CandidateRequirement",
        "AtomicRequirement",
        "TestObligation",
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
