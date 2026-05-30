from __future__ import annotations

import hashlib
from pathlib import Path

from ai_testgen.artifact_store import ArtifactStore, ArtifactStoreError, StoredArtifact
from ai_testgen.project_config import PROJECT_CONFIG_STAGE, load_project_config
from ai_testgen.schemas import Document, ProjectConfig, SchemaValidationError


DOCUMENTS_STAGE = "01_documents"
DOCUMENTS_ARTIFACT_NAME = "documents"
SUPPORTED_TEXT_CONTENT_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


class DocumentIngestionError(Exception):
    """Base error for deterministic document ingestion failures."""


class MissingSourcePathError(DocumentIngestionError):
    """Raised when a configured source path does not exist."""


class SourcePathIsDirectoryError(DocumentIngestionError):
    """Raised when a single document path points to a directory."""


class UnsupportedDocumentTypeError(DocumentIngestionError):
    """Raised when a source document is not a supported v1 text format."""


class DocumentReadError(DocumentIngestionError):
    """Raised when a source document cannot be read from disk."""


class DocumentDecodingError(DocumentIngestionError):
    """Raised when a source document cannot be decoded as UTF-8."""


class EmptyDocumentError(DocumentIngestionError):
    """Raised when a source document has no non-whitespace content."""


class InvalidDocumentError(DocumentIngestionError):
    """Raised when a generated Document fails the C01 schema."""


class DocumentPersistenceError(DocumentIngestionError):
    """Raised when the documents artifact cannot be persisted."""


def create_document_records(
    config: ProjectConfig,
    *,
    source_base_dir: str | Path | None = None,
) -> list[Document]:
    base_dir = _base_dir(source_base_dir)
    source_files = _discover_source_files(config, base_dir)
    return [
        ingest_document_file(
            source_file,
            config.project_id,
            source_base_dir=base_dir,
            document_id=f"doc_{index:03d}",
        )
        for index, source_file in enumerate(source_files, start=1)
    ]


def create_document_collection(
    config: ProjectConfig,
    *,
    source_base_dir: str | Path | None = None,
) -> dict:
    documents = create_document_records(config, source_base_dir=source_base_dir)
    return {
        "project_id": config.project_id,
        "documents": [document.to_dict() for document in documents],
    }


def ingest_document_file(
    source_path: str | Path,
    project_id: str,
    *,
    source_base_dir: str | Path | None = None,
    document_id: str = "doc_001",
) -> Document:
    base_dir = _base_dir(source_base_dir)
    path = _resolve_source_path(source_path, base_dir)
    _validate_source_file(path)

    content = _read_source_bytes(path)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentDecodingError(f"Source document must be UTF-8 text: {path}") from exc

    if not text.strip():
        raise EmptyDocumentError(f"Source document is empty: {path}")

    data = {
        "document_id": document_id,
        "project_id": project_id,
        "source_path": _stored_source_path(path, base_dir),
        "title": _title_from_path(path),
        "content_checksum": _checksum_bytes(content),
        "ingestion_status": "loaded",
        "content_type": SUPPORTED_TEXT_CONTENT_TYPES[path.suffix.lower()],
        "size_bytes": len(content),
        "metadata": {"encoding": "utf-8"},
    }
    try:
        return Document.from_dict(data)
    except SchemaValidationError as exc:
        raise InvalidDocumentError(f"Invalid Document data for {path}: {exc}") from exc


def ingest_documents(
    config: ProjectConfig,
    run_id: str,
    *,
    artifact_root: str | Path | None = None,
    source_base_dir: str | Path | None = None,
) -> StoredArtifact:
    collection = create_document_collection(config, source_base_dir=source_base_dir)
    store = ArtifactStore(artifact_root or config.artifact_root or "artifacts")
    try:
        return store.write_json(
            config.project_id,
            run_id,
            DOCUMENTS_STAGE,
            DOCUMENTS_ARTIFACT_NAME,
            collection,
        )
    except ArtifactStoreError as exc:
        raise DocumentPersistenceError(f"Failed to save documents artifact: {exc}") from exc


def ingest_documents_from_config_artifact(config_path: str | Path) -> StoredArtifact:
    path = Path(config_path)
    config = load_project_config(path)
    artifact_root, run_id = _artifact_context_from_config_path(path, config)
    return ingest_documents(config, run_id=run_id, artifact_root=artifact_root)


def _discover_source_files(config: ProjectConfig, base_dir: Path) -> list[Path]:
    if not config.source_paths:
        raise MissingSourcePathError("ProjectConfig.source_paths must include at least one source path")

    discovered: list[Path] = []
    seen: set[Path] = set()
    for configured_path in config.source_paths:
        path = _resolve_source_path(configured_path, base_dir)
        if not path.exists():
            raise MissingSourcePathError(f"Source path not found: {configured_path}")
        candidates = _directory_candidates(path) if path.is_dir() else [path]
        for candidate in candidates:
            _validate_supported_type(candidate)
            key = candidate.resolve(strict=True)
            if key in seen:
                continue
            seen.add(key)
            discovered.append(candidate)

    if not discovered:
        raise MissingSourcePathError("No source documents found in ProjectConfig.source_paths")
    return sorted(discovered, key=lambda item: _stored_source_path(item, base_dir))


def _directory_candidates(path: Path) -> list[Path]:
    candidates = sorted(
        (
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_TEXT_CONTENT_TYPES
        ),
        key=lambda item: item.as_posix(),
    )
    if not candidates:
        raise MissingSourcePathError(f"No source documents found under directory: {path}")
    return candidates


def _validate_source_file(path: Path) -> None:
    if not path.exists():
        raise MissingSourcePathError(f"Source path not found: {path}")
    if path.is_dir():
        raise SourcePathIsDirectoryError(f"Expected a source document file, got directory: {path}")
    _validate_supported_type(path)


def _validate_supported_type(path: Path) -> None:
    if path.suffix.lower() not in SUPPORTED_TEXT_CONTENT_TYPES:
        supported = ", ".join(sorted(SUPPORTED_TEXT_CONTENT_TYPES))
        raise UnsupportedDocumentTypeError(
            f"Unsupported source document type for {path}; supported extensions: {supported}"
        )


def _read_source_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DocumentReadError(f"Unable to read source document: {path}") from exc


def _resolve_source_path(source_path: str | Path, base_dir: Path) -> Path:
    path = Path(source_path)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve(strict=False)


def _stored_source_path(path: Path, base_dir: Path) -> str:
    resolved_path = path.resolve(strict=False)
    resolved_base = base_dir.resolve(strict=False)
    try:
        return resolved_path.relative_to(resolved_base).as_posix()
    except ValueError:
        return resolved_path.as_posix()


def _title_from_path(path: Path) -> str:
    words = path.stem.replace("-", " ").replace("_", " ").split()
    return " ".join(word.capitalize() for word in words) or path.name


def _base_dir(source_base_dir: str | Path | None) -> Path:
    return Path.cwd() if source_base_dir is None else Path(source_base_dir)


def _checksum_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _artifact_context_from_config_path(config_path: Path, config: ProjectConfig) -> tuple[Path, str]:
    if config_path.parent.name != PROJECT_CONFIG_STAGE:
        raise DocumentIngestionError(
            f"ProjectConfig artifact must be under {PROJECT_CONFIG_STAGE}: {config_path}"
        )
    run_dir = config_path.parent.parent
    project_dir = run_dir.parent
    if project_dir.name != config.project_id:
        raise DocumentIngestionError(
            f"ProjectConfig artifact project directory must match project_id {config.project_id}: {config_path}"
        )
    return project_dir.parent, run_dir.name
