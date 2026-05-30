from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from math import isfinite
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, TypeVar

from ai_testgen.schemas import SchemaModel


class ArtifactStoreError(Exception):
    """Base error for local artifact persistence failures."""


class ArtifactPathError(ArtifactStoreError):
    """Raised when an artifact path would violate store path rules."""


class ArtifactNotFoundError(ArtifactStoreError):
    """Raised when a requested artifact does not exist."""


class ArtifactExistsError(ArtifactStoreError):
    """Raised when a requested artifact version already exists."""


class MalformedArtifactError(ArtifactStoreError):
    """Raised when a stored artifact is not valid JSON."""


class ArtifactTypeError(ArtifactStoreError):
    """Raised when artifact data is not a supported JSON object shape."""


ModelT = TypeVar("ModelT", bound=SchemaModel)


@dataclass(frozen=True)
class StoredArtifact:
    path: Path
    checksum: str


class ArtifactStore:
    def __init__(self, artifact_root: str | Path = "artifacts") -> None:
        self.artifact_root = Path(artifact_root)

    def artifact_path(
        self,
        project_id: str,
        run_id: str,
        stage: str,
        artifact_name: str,
        *,
        version: int | None = None,
    ) -> Path:
        project_parts = _path_parts(project_id, "project_id", allow_nested=False)
        run_parts = _path_parts(run_id, "run_id", allow_nested=False)
        stage_parts = _path_parts(stage, "stage", allow_nested=True)
        artifact_parts = _path_parts(artifact_name, "artifact_name", allow_nested=False)
        artifact_stem = artifact_parts[0]
        if artifact_stem.endswith(".json"):
            raise ArtifactPathError("artifact_name must not include the .json suffix")

        version_number = _normalize_version(version)
        file_name = (
            f"{artifact_stem}.json"
            if version_number == 1
            else f"{artifact_stem}.v{version_number}.json"
        )
        path = self.artifact_root.joinpath(*project_parts, *run_parts, *stage_parts, file_name)
        return self._require_under_root(path)

    def write_json(
        self,
        project_id: str,
        run_id: str,
        stage: str,
        artifact_name: str,
        artifact: Mapping[str, Any] | SchemaModel,
        *,
        version: int | None = None,
    ) -> StoredArtifact:
        data = _artifact_data(artifact)
        path = (
            self._next_available_path(project_id, run_id, stage, artifact_name)
            if version is None
            else self.artifact_path(project_id, run_id, stage, artifact_name, version=version)
        )
        content = _stable_json_bytes(data)
        self._write_new_file(path, content)
        return StoredArtifact(path=path, checksum=_checksum_bytes(content))

    def read_json(
        self,
        project_id: str,
        run_id: str,
        stage: str,
        artifact_name: str,
        *,
        version: int | None = None,
    ) -> dict[str, Any]:
        path = self.artifact_path(project_id, run_id, stage, artifact_name, version=version)
        if not path.exists():
            raise ArtifactNotFoundError(f"Artifact not found: {path}")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MalformedArtifactError(f"Malformed JSON artifact: {path}") from exc

        if not isinstance(data, dict):
            raise ArtifactTypeError(f"Artifact JSON must be a mapping: {path}")
        return data

    def load_model(
        self,
        model_type: type[ModelT],
        project_id: str,
        run_id: str,
        stage: str,
        artifact_name: str,
        *,
        version: int | None = None,
    ) -> ModelT:
        if not isinstance(model_type, type) or not issubclass(model_type, SchemaModel):
            raise ArtifactTypeError("model_type must be a SchemaModel subclass")
        data = self.read_json(project_id, run_id, stage, artifact_name, version=version)
        return model_type.from_dict(data)

    def exists(
        self,
        project_id: str,
        run_id: str,
        stage: str,
        artifact_name: str,
        *,
        version: int | None = None,
    ) -> bool:
        return self.artifact_path(project_id, run_id, stage, artifact_name, version=version).exists()

    def checksum(
        self,
        project_id: str,
        run_id: str,
        stage: str,
        artifact_name: str,
        *,
        version: int | None = None,
    ) -> str:
        path = self.artifact_path(project_id, run_id, stage, artifact_name, version=version)
        if not path.exists():
            raise ArtifactNotFoundError(f"Artifact not found: {path}")
        return _checksum_bytes(path.read_bytes())

    def _next_available_path(self, project_id: str, run_id: str, stage: str, artifact_name: str) -> Path:
        version = 1
        while True:
            path = self.artifact_path(project_id, run_id, stage, artifact_name, version=version)
            if not path.exists():
                return path
            version += 1

    def _write_new_file(self, path: Path, content: bytes) -> None:
        if path.exists():
            raise ArtifactExistsError(f"Artifact already exists: {path}")

        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
            )
            temp_path = Path(temp_name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
            if path.exists():
                raise ArtifactExistsError(f"Artifact already exists: {path}")
            os.replace(temp_path, path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    def _require_under_root(self, path: Path) -> Path:
        root = self.artifact_root.resolve(strict=False)
        target = path.resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ArtifactPathError(f"Artifact path must remain under artifact_root: {path}") from exc
        return path


def _path_parts(value: str, field_name: str, *, allow_nested: bool) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactPathError(f"{field_name} must be a non-empty path segment")
    if value != value.strip():
        raise ArtifactPathError(f"{field_name} must not have leading or trailing whitespace")
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise ArtifactPathError(f"{field_name} must be relative")

    normalized = value.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ArtifactPathError(f"{field_name} must not contain path traversal")
    if not allow_nested and len(parts) != 1:
        raise ArtifactPathError(f"{field_name} must be a single path segment")
    return parts


def _normalize_version(version: int | None) -> int:
    if version is None:
        return 1
    if type(version) is not int or version < 1:
        raise ArtifactPathError("version must be a positive integer")
    return version


def _artifact_data(artifact: Mapping[str, Any] | SchemaModel) -> dict[str, Any]:
    if isinstance(artifact, SchemaModel):
        artifact = artifact.to_dict()
    if not isinstance(artifact, Mapping):
        raise ArtifactTypeError("artifact must be a mapping or SchemaModel")
    return _normalize_json_value(artifact, "artifact")


def _normalize_json_value(value: Any, field_name: str) -> Any:
    if value is None or isinstance(value, str) or type(value) in (bool, int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ArtifactTypeError(f"{field_name} must be finite")
        return value
    if isinstance(value, list):
        return [_normalize_json_value(item, f"{field_name}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ArtifactTypeError(f"{field_name} keys must be strings")
            normalized[key] = _normalize_json_value(item, f"{field_name}.{key}")
        return normalized
    raise ArtifactTypeError(f"{field_name} must be JSON-compatible")


def _stable_json_bytes(data: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _checksum_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"
