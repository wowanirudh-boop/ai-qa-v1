import hashlib
import inspect
import json
from pathlib import Path

import pytest

import ai_testgen.source_ledger as source_ledger
from ai_testgen.artifact_store import ArtifactStore
from ai_testgen.cli import main
from ai_testgen.schemas import SourcePackage
from ai_testgen.source_ledger import (
    EmptySourcePackageError,
    InvalidDocumentCollectionError,
    SourceDocumentChecksumMismatchError,
    SourceDocumentNotFoundError,
    build_source_package_from_documents_artifact,
    create_source_package,
)


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "source_ledger"


def write_source(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def checksum_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def checksum_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def document_data(**overrides: object) -> dict:
    data = {
        "document_id": "doc_001",
        "project_id": "demo_chatbot",
        "source_path": "docs/requirements.md",
        "title": "Requirements",
        "content_checksum": "sha256:document",
        "ingestion_status": "loaded",
        "content_type": "text/markdown",
        "metadata": {"encoding": "utf-8"},
    }
    data.update(overrides)
    return data


def document_collection(*documents: dict, project_id: str = "demo_chatbot") -> dict:
    return {"project_id": project_id, "documents": list(documents)}


def stable_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def test_chunking_happy_path_creates_valid_source_package_with_traceable_chunks(tmp_path):
    source_text = (
        "The bot must ask for an order number.\n\n"
        "The bot must explain when an order number is invalid.\n"
    )
    source_path = tmp_path / "docs" / "requirements.md"
    write_source(
        source_path,
        source_text,
    )

    package = create_source_package(
        document_collection(document_data(content_checksum=checksum_file(source_path))),
        source_base_dir=tmp_path,
    )

    assert isinstance(package, SourcePackage)
    assert package.to_dict() == {
        "source_package_id": "source_pkg_001",
        "project_id": "demo_chatbot",
        "document_ids": ["doc_001"],
        "chunks": [
            {
                "chunk_id": "chunk_001",
                "document_id": "doc_001",
                "sequence": 1,
                "text": "The bot must ask for an order number.",
                "checksum": checksum_text("The bot must ask for an order number."),
                "processing_status": "not_processed",
            },
            {
                "chunk_id": "chunk_002",
                "document_id": "doc_001",
                "sequence": 2,
                "text": "The bot must explain when an order number is invalid.",
                "checksum": checksum_text("The bot must explain when an order number is invalid."),
                "processing_status": "not_processed",
            },
        ],
        "checksum": package.checksum,
    }
    SourcePackage.from_dict(package.to_dict())
    assert {chunk.document_id for chunk in package.chunks} == {"doc_001"}


def test_empty_documents_do_not_produce_empty_chunks(tmp_path):
    empty_text = " \n\t\n"
    source_text = "The bot must greet the user.\n"
    empty_path = tmp_path / "docs" / "empty.md"
    source_path = tmp_path / "docs" / "requirements.md"
    write_source(empty_path, empty_text)
    write_source(source_path, source_text)
    documents = document_collection(
        document_data(
            document_id="doc_001",
            source_path="docs/empty.md",
            title="Empty",
            content_checksum=checksum_file(empty_path),
        ),
        document_data(
            document_id="doc_002",
            source_path="docs/requirements.md",
            content_checksum=checksum_file(source_path),
        ),
    )

    package = create_source_package(documents, source_base_dir=tmp_path)

    assert package.document_ids == ["doc_001", "doc_002"]
    assert [chunk.document_id for chunk in package.chunks] == ["doc_002"]
    assert [chunk.text for chunk in package.chunks] == ["The bot must greet the user."]


def test_all_empty_documents_fail_before_writing_invalid_source_package(tmp_path):
    empty_text = " \n\t\n"
    empty_path = tmp_path / "docs" / "empty.md"
    write_source(empty_path, empty_text)

    with pytest.raises(EmptySourcePackageError, match="No source chunks"):
        create_source_package(
            document_collection(
                document_data(
                    source_path="docs/empty.md",
                    content_checksum=checksum_file(empty_path),
                )
            ),
            source_base_dir=tmp_path,
        )


def test_chunk_ids_and_checksums_are_stable(tmp_path):
    source_text = "First requirement.\n\nSecond requirement.\n"
    source_path = tmp_path / "docs" / "requirements.md"
    write_source(
        source_path,
        source_text,
    )
    documents = document_collection(document_data(content_checksum=checksum_file(source_path)))

    first = create_source_package(documents, source_base_dir=tmp_path)
    second = create_source_package(documents, source_base_dir=tmp_path)

    assert [chunk.chunk_id for chunk in first.chunks] == [chunk.chunk_id for chunk in second.chunks]
    assert [chunk.checksum for chunk in first.chunks] == [chunk.checksum for chunk in second.chunks]
    assert first.checksum == second.checksum


def test_document_collection_validation_rejects_bad_collection_shape(tmp_path):
    write_source(tmp_path / "docs" / "requirements.md", "Requirement.\n")

    with pytest.raises(InvalidDocumentCollectionError, match="documents"):
        create_source_package({"project_id": "demo_chatbot"}, source_base_dir=tmp_path)

    with pytest.raises(InvalidDocumentCollectionError, match="project_id"):
        create_source_package(
            document_collection(document_data(project_id="other_project")),
            source_base_dir=tmp_path,
        )


def test_missing_referenced_source_document_fails_clearly(tmp_path):
    with pytest.raises(SourceDocumentNotFoundError, match="Source document not found"):
        create_source_package(document_collection(document_data()), source_base_dir=tmp_path)


def test_source_document_checksum_mismatch_fails_clearly(tmp_path):
    write_source(tmp_path / "docs" / "requirements.md", "Changed after ingestion.\n")

    with pytest.raises(SourceDocumentChecksumMismatchError, match="checksum"):
        create_source_package(
            document_collection(
                document_data(content_checksum=checksum_text("Original ingested content.\n"))
            ),
            source_base_dir=tmp_path,
        )


def test_source_package_serialization_matches_golden_fixture():
    documents = json.loads((GOLDEN_DIR / "documents.json").read_text(encoding="utf-8"))

    package = create_source_package(documents, source_base_dir=GOLDEN_DIR)

    assert stable_json(package.to_dict()) == (GOLDEN_DIR / "source_package.json").read_text(
        encoding="utf-8"
    )


def test_build_source_package_persists_only_c05_artifact(tmp_path):
    source_path = tmp_path / "docs" / "requirements.md"
    source_text = "The bot must greet the user.\n"
    write_source(source_path, source_text)
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    documents = document_collection(
        document_data(
            source_path=source_path.as_posix(),
            content_checksum=checksum_file(source_path),
        )
    )
    documents_artifact = store.write_json(
        "demo_chatbot",
        "run_001",
        "01_documents",
        "documents",
        documents,
    )

    written = build_source_package_from_documents_artifact(documents_artifact.path)

    assert written.path == artifact_root / "demo_chatbot" / "run_001" / "02_source_package" / "source_package.json"
    assert SourcePackage.from_dict(json.loads(written.path.read_text(encoding="utf-8")))
    files = sorted(path.relative_to(artifact_root).as_posix() for path in artifact_root.rglob("*") if path.is_file())
    assert files == [
        "demo_chatbot/run_001/01_documents/documents.json",
        "demo_chatbot/run_001/02_source_package/source_package.json",
    ]


def test_build_source_package_loads_documents_through_artifact_store(tmp_path, monkeypatch):
    source_path = tmp_path / "docs" / "requirements.md"
    source_text = "The bot must greet the user.\n"
    write_source(source_path, source_text)
    artifact_root = tmp_path / "artifacts"
    documents_path = artifact_root / "demo_chatbot" / "run_001" / "01_documents" / "documents.json"
    documents_path.parent.mkdir(parents=True)
    documents_path.write_text("{not valid json", encoding="utf-8")
    documents = document_collection(
        document_data(
            source_path=source_path.as_posix(),
            content_checksum=checksum_file(source_path),
        )
    )
    calls = []

    def fake_read_json(self, project_id, run_id, stage, artifact_name, *, version=None):
        calls.append((self.artifact_root, project_id, run_id, stage, artifact_name, version))
        return documents

    monkeypatch.setattr(source_ledger.ArtifactStore, "read_json", fake_read_json)

    written = build_source_package_from_documents_artifact(documents_path)

    assert written.path == artifact_root / "demo_chatbot" / "run_001" / "02_source_package" / "source_package.json"
    assert calls == [(artifact_root, "demo_chatbot", "run_001", "01_documents", "documents", None)]


def test_cli_build_source_package_reads_documents_artifact_and_writes_source_package(tmp_path, capsys):
    source_path = tmp_path / "docs" / "requirements.md"
    source_text = "The bot must greet the user.\n"
    write_source(source_path, source_text)
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    documents_artifact = store.write_json(
        "demo_chatbot",
        "run_001",
        "01_documents",
        "documents",
        document_collection(
                document_data(
                    source_path=source_path.as_posix(),
                    content_checksum=checksum_file(source_path),
                )
            ),
    )

    exit_code = main(["build-source-package", "--documents", str(documents_artifact.path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "source_package.json" in captured.out
    assert captured.err == ""
    assert (artifact_root / "demo_chatbot" / "run_001" / "02_source_package" / "source_package.json").exists()


def test_c05_implementation_has_no_future_component_or_model_dependencies():
    source = inspect.getsource(source_ledger)

    for forbidden in (
        "CandidateRequirement",
        "AtomicRequirement",
        "TestObligation",
        "DraftTestSuite",
        "SkillRun",
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
