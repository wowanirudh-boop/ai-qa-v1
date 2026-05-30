# C00 Bootstrap and Architecture Docs

## Purpose

Create the permanent architecture documentation and repository scaffolding for v1. This component is documentation-only.

## Inputs

- Empty or existing repository.
- Bootstrap prompt describing architecture rules, pipeline, contracts, and component boundaries.

Input artifact path conventions:

- None. This component does not consume runtime artifacts.

## Outputs

- Repository docs.
- Directory structure.
- Empty package marker files.
- Optional minimal project metadata for future tests.

Output artifact path conventions:

- None. This component does not create runtime artifacts under `artifacts/{project_id}/{run_id}/`.

## Data contracts used

- None implemented.
- `docs/DATA_CONTRACTS.md` documents all canonical v1 contracts for future components.

## Files/modules to create

May create:

- `AGENTS.md`
- `README.md`
- `docs/*.md`
- `docs/components/*.md`
- `src/ai_testgen/__init__.py`
- `tests/unit/`
- `tests/unit/fixtures/golden/`
- `examples/demo_project/docs/`
- `skills/`
- minimal `pyproject.toml` if useful for future test commands

## CLI command

None.

## Runtime skills used

None.

## Deterministic code responsibilities

- Create requested documentation and scaffolding.
- Keep `AGENTS.md` short and operational.
- Preserve the hard architecture rules.
- Avoid production business logic.

## Validation rules

- All requested docs exist.
- All requested component specs exist.
- Source package contains only marker files, not component implementation.
- No LLM calls, external service calls, or runtime behavior are added.

## Required tests

- No executable tests are required for this architecture-only component.
- Verify with safe inspection commands and `git status --short`.

## Golden fixtures

None.

## Non-goals

Must not implement:

- schemas
- artifact store
- CLI orchestration
- requirement extraction
- test generation
- skill execution
- executor exports

## Definition of done

- All requested files and directories exist.
- Architecture rules, data contracts, TDD rules, workflow, pipeline, and C00-C15 specs are documented.
- Safe inspection commands have been run.
- Tests are not run unless executable implementation exists.

