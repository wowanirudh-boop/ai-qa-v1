from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Mapping

from ai_testgen.artifact_store import (
    ArtifactNotFoundError,
    ArtifactStore,
    ArtifactStoreError,
    ArtifactTypeError,
    MalformedArtifactError,
    StoredArtifact,
)
from ai_testgen.schemas import ProjectConfig, SchemaValidationError


PROJECT_CONFIG_STAGE = "00_project_config"
PROJECT_CONFIG_ARTIFACT_NAME = "project_config"


class ProjectConfigError(Exception):
    """Base error for project configuration failures."""


class ProjectConfigFileNotFoundError(ProjectConfigError):
    """Raised when a project config file or artifact is missing."""


class MalformedProjectConfigError(ProjectConfigError):
    """Raised when project config JSON cannot be parsed."""


class InvalidProjectConfigError(ProjectConfigError):
    """Raised when project config data fails the C01 schema."""


class ProjectConfigPersistenceError(ProjectConfigError):
    """Raised when project config artifact persistence fails."""


def load_project_config(config_path: str | Path) -> ProjectConfig:
    path = Path(config_path)
    if not path.exists():
        raise ProjectConfigFileNotFoundError(f"ProjectConfig file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise MalformedProjectConfigError(f"Malformed ProjectConfig JSON: {path}") from exc

    return validate_project_config(data)


def validate_project_config(data: Mapping[str, Any]) -> ProjectConfig:
    try:
        return ProjectConfig.from_dict(data)
    except SchemaValidationError as exc:
        raise InvalidProjectConfigError(f"Invalid ProjectConfig: {exc}") from exc


def save_project_config(
    config: ProjectConfig,
    run_id: str,
    *,
    artifact_root: str | Path | None = None,
) -> StoredArtifact:
    validated = validate_project_config(config.to_dict())
    store = ArtifactStore(artifact_root or validated.artifact_root or "artifacts")
    try:
        return store.write_json(
            validated.project_id,
            run_id,
            PROJECT_CONFIG_STAGE,
            PROJECT_CONFIG_ARTIFACT_NAME,
            validated,
        )
    except ArtifactStoreError as exc:
        raise ProjectConfigPersistenceError(f"Failed to save ProjectConfig artifact: {exc}") from exc


def load_saved_project_config(
    project_id: str,
    run_id: str,
    *,
    artifact_root: str | Path = "artifacts",
    version: int | None = None,
) -> ProjectConfig:
    store = ArtifactStore(artifact_root)
    try:
        return store.load_model(
            ProjectConfig,
            project_id,
            run_id,
            PROJECT_CONFIG_STAGE,
            PROJECT_CONFIG_ARTIFACT_NAME,
            version=version,
        )
    except ArtifactNotFoundError as exc:
        raise ProjectConfigFileNotFoundError(f"Persisted ProjectConfig not found: {exc}") from exc
    except MalformedArtifactError as exc:
        raise MalformedProjectConfigError(f"Malformed persisted ProjectConfig JSON: {exc}") from exc
    except (ArtifactTypeError, SchemaValidationError) as exc:
        raise InvalidProjectConfigError(f"Invalid persisted ProjectConfig: {exc}") from exc
    except ArtifactStoreError as exc:
        raise ProjectConfigPersistenceError(f"Failed to load persisted ProjectConfig artifact: {exc}") from exc
