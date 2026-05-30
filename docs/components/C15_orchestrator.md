# C15 End-to-End Orchestrator

## Purpose

Own CLI orchestration across completed components.

## Inputs

- User-supplied project config.
- Source documents.
- Implemented component modules.

Input artifact path conventions:

- User config defaults to `project_config.json`.
- Runtime artifacts are read from and written to `artifacts/{project_id}/{run_id}/`.

## Outputs

- Full pipeline artifact set.
- `PipelineRunState`.
- Final review and export artifacts when requested and eligible.

Output artifact path conventions:

- `artifacts/{project_id}/{run_id}/pipeline_run_state.json`
- Stage outputs follow `docs/PIPELINE.md`.

## Data contracts used

- `ProjectConfig`
- `Document`
- `SourcePackage`
- `CandidateRequirementPackage`
- `AtomicRequirementLedger`
- `GovernedRequirementLedger`
- `TestObligationLedger`
- `DraftTestSuite`
- `ValidatedTestSuite`
- `CoverageReport`
- `ReviewReportMetadata`
- `ExecutorExportPackage`
- `PipelineRunState`

## Files/modules to create

May create:

- `src/ai_testgen/cli.py`
- `src/ai_testgen/orchestrator.py`
- `tests/unit/test_orchestrator.py`
- `tests/unit/test_cli.py`
- `tests/unit/fixtures/golden/orchestrator/`

## CLI command

`ai-testgen run --config project_config.json --run-id run_001`

## Runtime skills used

None directly. The orchestrator may trigger components that use Skill Runtime, but it must not call runtime skills or LLMs directly.

## Deterministic code responsibilities

- Call completed components in pipeline order.
- Pass artifact paths and validated contracts between components.
- Track run state.
- Stop on validation failures.
- Avoid bypassing component contracts.

## Validation rules

- Must not skip required prior stages.
- Must not call runtime skills directly.
- Must not implement business logic owned by earlier components.
- Must persist run state after each completed stage.
- Must fail clearly when a required component is not implemented.

## Required tests

- CLI smoke test for help or dry-run behavior.
- Happy path orchestration using fake component adapters.
- Failure stops the pipeline and records failed stage.
- Run state records completed stages.
- Orchestrator does not bypass component interfaces.

## Golden fixtures

Useful when enough components exist. Include a small end-to-end artifact tree produced by fake adapters.

## Non-goals

Must not implement:

- schema rules owned by C01
- artifact store internals owned by C02
- business transformations owned by C04-C14
- direct runtime skill calls
- direct external service calls

## Definition of done

- CLI can orchestrate implemented components in order.
- Tests prove run-state behavior and failure handling.
- Orchestrator remains thin and contract-driven.

