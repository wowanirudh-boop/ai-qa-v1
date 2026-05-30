# C03 Project Configuration

## Purpose

Own loading, validating, and saving `ProjectConfig`.

## Inputs

- User-authored project config JSON.
- Optional explicit artifact root and run ID.

Input artifact path conventions:

- Source config may come from `project_config.json` or a user-supplied path.

## Outputs

- Validated `ProjectConfig`.
- Persisted project config artifact.

Output artifact path conventions:

- `artifacts/{project_id}/{run_id}/00_project_config/project_config.json`

## Data contracts used

- `ProjectConfig`

## Files/modules to create

May create:

- `src/ai_testgen/project_config.py`
- `tests/unit/test_project_config.py`
- `tests/unit/fixtures/golden/project_config/`

## CLI command

`ai-testgen config validate --config project_config.json --run-id run_001`

## Runtime skills used

None.

## Deterministic code responsibilities

- Load user config JSON.
- Validate required `ProjectConfig` fields.
- Apply only documented conservative defaults.
- Save the validated config through C02 Artifact Store when available.

## Validation rules

- `project_id`, `bot_name`, `target_url`, `coverage_policy`, and `approval_policy` are required.
- Unknown policy fields may be rejected unless documented in `metadata`.
- Config validation must not ingest documents or create requirements.

## Required tests

- Valid config loads.
- Missing required fields fail.
- Config saves to expected artifact path.
- CLI smoke test if CLI exists for this component.

## Golden fixtures

Useful. Include valid and invalid project config examples.

## Non-goals

Must not implement:

- document ingestion
- source chunking
- requirement extraction
- test generation
- runtime skill calls

## Definition of done

- Project config can be loaded, validated, and saved.
- Tests prove required fields and artifact path behavior.
- No downstream pipeline artifacts are created.

