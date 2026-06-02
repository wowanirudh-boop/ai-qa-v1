from __future__ import annotations

import os
from pathlib import Path

from ai_testgen.artifact_store import ArtifactNotFoundError, ArtifactStore, ArtifactStoreError
from ai_testgen.codex_cli_adapter import CODEX_CLI_ADAPTER_NAME, CodexCliSkillAdapter
from ai_testgen.schemas import ProjectConfig, SchemaValidationError
from ai_testgen.skill_runtime import SkillRuntime, SkillRuntimeError


SKILL_RUNTIME_ADAPTER_ENV = "AI_TESTGEN_SKILL_RUNTIME_ADAPTER"
PROJECT_CONFIG_ADAPTER_METADATA_KEY = "skill_runtime_adapter"


class SkillRuntimeAdapterConfigurationError(SkillRuntimeError):
    """Raised when explicit skill runtime adapter configuration is invalid."""


def create_skill_runtime_for_run(
    *,
    artifact_root: str | Path,
    project_id: str,
    run_id: str,
    adapter_name: str | None = None,
) -> SkillRuntime:
    resolved_adapter_name = _resolve_adapter_name(
        artifact_root=artifact_root,
        project_id=project_id,
        run_id=run_id,
        adapter_name=adapter_name,
    )
    if resolved_adapter_name is None:
        return SkillRuntime(artifact_root=artifact_root)
    if resolved_adapter_name == CODEX_CLI_ADAPTER_NAME:
        return SkillRuntime(artifact_root=artifact_root, adapter=CodexCliSkillAdapter())
    raise SkillRuntimeAdapterConfigurationError(
        f"Unknown skill runtime adapter: {resolved_adapter_name}"
    )


def _resolve_adapter_name(
    *,
    artifact_root: str | Path,
    project_id: str,
    run_id: str,
    adapter_name: str | None,
) -> str | None:
    explicit = _normalized_adapter_name(adapter_name)
    if explicit is not None:
        return explicit

    from_env = _normalized_adapter_name(os.environ.get(SKILL_RUNTIME_ADAPTER_ENV))
    if from_env is not None:
        return from_env

    return _adapter_name_from_project_config(
        artifact_root=artifact_root,
        project_id=project_id,
        run_id=run_id,
    )


def _adapter_name_from_project_config(
    *,
    artifact_root: str | Path,
    project_id: str,
    run_id: str,
) -> str | None:
    store = ArtifactStore(artifact_root)
    try:
        config = store.load_model(
            ProjectConfig,
            project_id,
            run_id,
            "00_project_config",
            "project_config",
        )
    except ArtifactNotFoundError:
        return None
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise SkillRuntimeAdapterConfigurationError(
            f"Invalid ProjectConfig adapter configuration: {exc}"
        ) from exc

    if not config.metadata:
        return None
    return _normalized_adapter_name(config.metadata.get(PROJECT_CONFIG_ADAPTER_METADATA_KEY))


def _normalized_adapter_name(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SkillRuntimeAdapterConfigurationError(
            "skill runtime adapter name must be a non-empty string"
        )
    return value.strip()
