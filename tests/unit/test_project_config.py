import json
from pathlib import Path

import pytest

from ai_testgen.cli import main
from ai_testgen.project_config import (
    InvalidProjectConfigError,
    MalformedProjectConfigError,
    ProjectConfigError,
    ProjectConfigFileNotFoundError,
    load_project_config,
    load_saved_project_config,
    save_project_config,
    validate_project_config,
)


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


def write_config(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_project_config_validates_and_preserves_optional_fields(tmp_path):
    artifact_root = tmp_path / "artifacts"
    data = valid_config_data(
        description="Demo project",
        source_paths=["docs/requirements.md"],
        artifact_root=str(artifact_root),
        metadata={"owner": "qa", "priority": 1},
    )
    config_path = tmp_path / "project_config.json"
    write_config(config_path, data)

    config = load_project_config(config_path)

    assert config.to_dict() == data


@pytest.mark.parametrize(
    "field_name",
    ["project_id", "bot_name", "target_url", "coverage_policy", "approval_policy"],
)
def test_validate_project_config_rejects_missing_required_fields(field_name):
    data = valid_config_data()
    data.pop(field_name)

    with pytest.raises(InvalidProjectConfigError, match=field_name):
        validate_project_config(data)


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("project_id", ""),
        ("bot_name", " "),
        ("target_url", ""),
    ],
)
def test_validate_project_config_rejects_empty_required_strings(field_name, field_value):
    data = valid_config_data(**{field_name: field_value})

    with pytest.raises(InvalidProjectConfigError, match=field_name):
        validate_project_config(data)


def test_load_project_config_rejects_malformed_json(tmp_path):
    config_path = tmp_path / "project_config.json"
    config_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(MalformedProjectConfigError, match="Malformed ProjectConfig JSON"):
        load_project_config(config_path)


def test_load_project_config_rejects_schema_invalid_data(tmp_path):
    config_path = tmp_path / "project_config.json"
    write_config(config_path, valid_config_data(coverage_policy=["not", "a", "mapping"]))

    with pytest.raises(InvalidProjectConfigError, match="coverage_policy"):
        load_project_config(config_path)


def test_load_project_config_rejects_unknown_fields_through_c01_schema(tmp_path):
    config_path = tmp_path / "project_config.json"
    write_config(config_path, valid_config_data(extra_field=True))

    with pytest.raises(InvalidProjectConfigError, match="Unknown field"):
        load_project_config(config_path)


def test_load_project_config_missing_file_behavior(tmp_path):
    missing_config = tmp_path / "missing_project_config.json"

    with pytest.raises(ProjectConfigFileNotFoundError, match="ProjectConfig file not found"):
        load_project_config(missing_config)


def test_save_and_load_project_config_round_trip_preserves_validated_config(tmp_path):
    artifact_root = tmp_path / "artifacts"
    data = valid_config_data(
        description="Demo project",
        source_paths=["docs/requirements.md", "docs/policy.md"],
        artifact_root=str(artifact_root),
        metadata={"custom": {"kept": True}},
    )
    config = validate_project_config(data)

    written = save_project_config(config, run_id="run_001")
    loaded = load_saved_project_config(
        project_id="demo_chatbot",
        run_id="run_001",
        artifact_root=artifact_root,
    )

    assert written.path == (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "00_project_config"
        / "project_config.json"
    )
    assert loaded == config
    assert loaded.to_dict() == data


def test_save_project_config_serializes_deterministically(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config = validate_project_config(valid_config_data(artifact_root=str(artifact_root)))

    written = save_project_config(config, run_id="run_001")

    assert written.path.read_text(encoding="utf-8") == (
        json.dumps(
            config.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def test_save_project_config_uses_c02_versioning_for_repeated_writes(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config = validate_project_config(valid_config_data(artifact_root=str(artifact_root)))

    first = save_project_config(config, run_id="run_001")
    second = save_project_config(config, run_id="run_001")

    assert first.path.name == "project_config.json"
    assert second.path.name == "project_config.v2.json"


def test_save_project_config_does_not_create_future_component_artifacts(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config = validate_project_config(valid_config_data(artifact_root=str(artifact_root)))

    save_project_config(config, run_id="run_001")

    files = sorted(path.relative_to(artifact_root).as_posix() for path in artifact_root.rglob("*") if path.is_file())
    assert files == ["demo_chatbot/run_001/00_project_config/project_config.json"]


def test_save_project_config_wraps_artifact_store_errors_as_project_config_error(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config = validate_project_config(valid_config_data(artifact_root=str(artifact_root)))

    with pytest.raises(ProjectConfigError, match="Failed to save ProjectConfig.*run_id"):
        save_project_config(config, run_id="../run_001")


def test_load_saved_project_config_wraps_artifact_store_errors_as_project_config_error(tmp_path):
    artifact_root = tmp_path / "artifacts"

    with pytest.raises(ProjectConfigError, match="Failed to load persisted ProjectConfig.*run_id"):
        load_saved_project_config("demo_chatbot", "../run_001", artifact_root=artifact_root)


def test_cli_config_validate_smoke_saves_validated_config(tmp_path, capsys):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, valid_config_data(artifact_root=str(artifact_root)))

    exit_code = main(["config", "validate", "--config", str(config_path), "--run-id", "run_001"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "project_config.json" in output
    assert (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "00_project_config"
        / "project_config.json"
    ).exists()


def test_cli_config_validate_reports_missing_config_file(tmp_path, capsys):
    missing_config = tmp_path / "missing_project_config.json"

    exit_code = main(["config", "validate", "--config", str(missing_config), "--run-id", "run_001"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "error:" in captured.err
    assert "ProjectConfig file not found" in captured.err


def test_cli_config_validate_reports_malformed_json(tmp_path, capsys):
    config_path = tmp_path / "project_config.json"
    config_path.write_text("{not valid json", encoding="utf-8")

    exit_code = main(["config", "validate", "--config", str(config_path), "--run-id", "run_001"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "error:" in captured.err
    assert "Malformed ProjectConfig JSON" in captured.err


def test_cli_config_validate_reports_schema_invalid_config(tmp_path, capsys):
    config_path = tmp_path / "project_config.json"
    write_config(config_path, valid_config_data(target_url=""))

    exit_code = main(["config", "validate", "--config", str(config_path), "--run-id", "run_001"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "error:" in captured.err
    assert "Invalid ProjectConfig" in captured.err
    assert "target_url" in captured.err
