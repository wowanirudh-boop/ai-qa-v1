from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from ai_testgen.artifact_store import ArtifactStore, ArtifactStoreError, StoredArtifact
from ai_testgen.schemas import (
    Document,
    DocumentIngestionStatus,
    SchemaValidationError,
    SourceChunk,
    SourceChunkProcessingStatus,
    SourcePackage,
)


DOCUMENTS_STAGE = "01_documents"
SOURCE_PACKAGE_STAGE = "02_source_package"
SOURCE_PACKAGE_ARTIFACT_NAME = "source_package"
SOURCE_PACKAGE_ID = "source_pkg_001"


class SourceLedgerError(Exception):
    """Base error for deterministic source ledger failures."""


class InvalidDocumentCollectionError(SourceLedgerError):
    """Raised when the documents artifact is not a valid C04 collection."""


class DocumentCollectionArtifactError(SourceLedgerError):
    """Raised when the documents artifact cannot be read."""


class SourceDocumentNotFoundError(SourceLedgerError):
    """Raised when a Document points to a missing source file."""


class SourceDocumentIsDirectoryError(SourceLedgerError):
    """Raised when a Document source path points to a directory."""


class SourceDocumentReadError(SourceLedgerError):
    """Raised when source content cannot be read."""


class SourceDocumentChecksumMismatchError(SourceLedgerError):
    """Raised when source content no longer matches its Document record."""


class SourceDocumentDecodingError(SourceLedgerError):
    """Raised when source content is not UTF-8 text."""


class EmptySourcePackageError(SourceLedgerError):
    """Raised when no non-empty chunks can be produced."""


class InvalidSourcePackageError(SourceLedgerError):
    """Raised when generated source package data violates the schema."""


class SourcePackagePersistenceError(SourceLedgerError):
    """Raised when the source package cannot be persisted."""


def create_source_package(
    document_collection: Mapping[str, Any],
    *,
    source_base_dir: str | Path | None = None,
) -> SourcePackage:
    project_id, documents = _validate_document_collection(document_collection)
    chunks = create_source_chunks(documents, source_base_dir=source_base_dir)
    if not chunks:
        raise EmptySourcePackageError("No source chunks were produced from the document collection")

    document_ids = [document.document_id for document in documents]
    data = {
        "source_package_id": SOURCE_PACKAGE_ID,
        "project_id": project_id,
        "document_ids": document_ids,
        "chunks": [chunk.to_dict() for chunk in chunks],
    }
    data["checksum"] = _checksum_json(data)

    try:
        return SourcePackage.from_dict(data)
    except SchemaValidationError as exc:
        raise InvalidSourcePackageError(f"Invalid SourcePackage data: {exc}") from exc


def create_source_chunks(
    documents: list[Document],
    *,
    source_base_dir: str | Path | None = None,
) -> list[SourceChunk]:
    base_dir = _base_dir(source_base_dir)
    chunks: list[SourceChunk] = []
    next_sequence = 1

    for document in documents:
        text = _read_source_text(
            _resolve_source_path(document.source_path, base_dir),
            expected_checksum=document.content_checksum,
        )
        for chunk_text in _split_chunks(text):
            chunk_data = {
                "chunk_id": f"chunk_{next_sequence:03d}",
                "document_id": document.document_id,
                "sequence": next_sequence,
                "text": chunk_text,
                "checksum": _checksum_text(chunk_text),
                "processing_status": SourceChunkProcessingStatus.NOT_PROCESSED.value,
            }
            try:
                chunks.append(SourceChunk.from_dict(chunk_data))
            except SchemaValidationError as exc:
                raise InvalidSourcePackageError(f"Invalid SourceChunk data: {exc}") from exc
            next_sequence += 1

    return chunks


def build_source_package_from_documents_artifact(
    documents_path: str | Path,
    *,
    source_base_dir: str | Path | None = None,
) -> StoredArtifact:
    path = Path(documents_path)
    artifact_root, artifact_project_id, run_id = _artifact_context_from_documents_path(path)
    collection = _read_document_collection_artifact(
        artifact_root,
        project_id=artifact_project_id,
        run_id=run_id,
    )
    package = create_source_package(collection, source_base_dir=source_base_dir)
    if package.project_id != artifact_project_id:
        raise DocumentCollectionArtifactError(
            f"Documents artifact project directory must match project_id {package.project_id}: {path}"
        )
    return save_source_package(package, run_id=run_id, artifact_root=artifact_root)


def save_source_package(
    package: SourcePackage,
    run_id: str,
    *,
    artifact_root: str | Path | None = None,
) -> StoredArtifact:
    store = ArtifactStore(artifact_root or "artifacts")
    try:
        return store.write_json(
            package.project_id,
            run_id,
            SOURCE_PACKAGE_STAGE,
            SOURCE_PACKAGE_ARTIFACT_NAME,
            package,
        )
    except ArtifactStoreError as exc:
        raise SourcePackagePersistenceError(f"Failed to save SourcePackage artifact: {exc}") from exc


def _validate_document_collection(collection: Mapping[str, Any]) -> tuple[str, list[Document]]:
    if not isinstance(collection, Mapping):
        raise InvalidDocumentCollectionError("Document collection must be a mapping")

    project_id = collection.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise InvalidDocumentCollectionError("Document collection project_id is required")

    raw_documents = collection.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise InvalidDocumentCollectionError("Document collection documents must be a non-empty list")

    documents: list[Document] = []
    document_ids: set[str] = set()
    for index, raw_document in enumerate(raw_documents):
        try:
            document = Document.from_dict(raw_document)
        except SchemaValidationError as exc:
            raise InvalidDocumentCollectionError(f"Invalid Document at documents[{index}]: {exc}") from exc

        if document.project_id != project_id:
            raise InvalidDocumentCollectionError("Document project_id must match collection project_id")
        if document.ingestion_status != DocumentIngestionStatus.LOADED:
            raise InvalidDocumentCollectionError("Only loaded documents can be chunked")
        if document.document_id in document_ids:
            raise InvalidDocumentCollectionError(f"Duplicate document_id in collection: {document.document_id}")
        document_ids.add(document.document_id)
        documents.append(document)

    return project_id, documents


def _read_document_collection_artifact(
    artifact_root: Path,
    *,
    project_id: str,
    run_id: str,
) -> dict[str, Any]:
    store = ArtifactStore(artifact_root)
    try:
        data = store.read_json(project_id, run_id, DOCUMENTS_STAGE, "documents")
    except ArtifactStoreError as exc:
        raise DocumentCollectionArtifactError(f"Failed to load documents artifact: {exc}") from exc

    if not isinstance(data, dict):
        raise InvalidDocumentCollectionError("Documents artifact JSON must be a mapping")
    return data


def _artifact_context_from_documents_path(path: Path) -> tuple[Path, str, str]:
    if path.name != "documents.json":
        raise DocumentCollectionArtifactError(f"Documents artifact must be named documents.json: {path}")
    if path.parent.name != DOCUMENTS_STAGE:
        raise DocumentCollectionArtifactError(
            f"Documents artifact must be under {DOCUMENTS_STAGE}: {path}"
        )
    run_dir = path.parent.parent
    project_dir = run_dir.parent
    return project_dir.parent, project_dir.name, run_dir.name


def _read_source_text(path: Path, *, expected_checksum: str) -> str:
    if not path.exists():
        raise SourceDocumentNotFoundError(f"Source document not found: {path}")
    if path.is_dir():
        raise SourceDocumentIsDirectoryError(f"Expected source document file, got directory: {path}")

    try:
        content = path.read_bytes()
    except OSError as exc:
        raise SourceDocumentReadError(f"Unable to read source document: {path}") from exc

    actual_checksum = _checksum_bytes(content)
    if actual_checksum != expected_checksum:
        raise SourceDocumentChecksumMismatchError(
            f"Source document checksum mismatch for {path}: expected {expected_checksum}, got {actual_checksum}"
        )

    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceDocumentDecodingError(f"Source document must be UTF-8 text: {path}") from exc


def _split_chunks(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return [
        chunk.strip()
        for chunk in re.split(r"\n\s*\n+", normalized)
        if chunk.strip()
    ]


def _resolve_source_path(source_path: str, base_dir: Path) -> Path:
    path = Path(source_path)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve(strict=False)


def _base_dir(source_base_dir: str | Path | None) -> Path:
    return Path.cwd() if source_base_dir is None else Path(source_base_dir)


def _checksum_text(text: str) -> str:
    return _checksum_bytes(text.encode("utf-8"))


def _checksum_json(data: Mapping[str, Any]) -> str:
    content = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _checksum_bytes(content)


def _checksum_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"
