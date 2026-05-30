# C14 Executor Export

## Purpose

Own creating `ExecutorExportPackage` from `ValidatedTestSuite`.

## Inputs

- `ValidatedTestSuite`
- `GovernedRequirementLedger`
- `TestObligationLedger`
- `ProjectConfig`

Input artifact path conventions:

- `artifacts/{project_id}/{run_id}/08_validated_tests/validated_test_suite.json`
- `artifacts/{project_id}/{run_id}/05_governed_requirements/governed_requirement_ledger.json`
- `artifacts/{project_id}/{run_id}/06_test_obligations/test_obligation_ledger.json`
- `artifacts/{project_id}/{run_id}/00_project_config/project_config.json`

## Outputs

- Executor-specific test files.
- `ExecutorExportPackage`.

Output artifact path conventions:

- `artifacts/{project_id}/{run_id}/10_executor_export/executor_export_package.json`
- `artifacts/{project_id}/{run_id}/10_executor_export/tests.json`

## Data contracts used

- `ProjectConfig`
- `ValidatedTestSuite`
- `TestCase`
- `GovernedRequirementLedger`
- `TestObligationLedger`
- `ExecutorExportPackage`

## Files/modules to create

May create:

- `src/ai_testgen/executor_export.py`
- `tests/unit/test_executor_export.py`
- `tests/unit/fixtures/golden/executor_export/`

## CLI command

`ai-testgen export --validated-suite artifacts/{project_id}/{run_id}/08_validated_tests/validated_test_suite.json`

## Runtime skills used

None.

## Deterministic code responsibilities

- Select only export eligible tests.
- Transform validated tests into executor format.
- Write export files.
- Create export package metadata.
- Preserve requirement and obligation IDs in exported records where supported.

## Validation rules

- Must export only eligible tests.
- Must not export tests linked to unknown requirements.
- Must not export tests linked to rejected requirements.
- Must not export tests linked to conflicting requirements.
- Must not export tests without non-empty `source_refs`.
- Exported test IDs must be a subset of the validated suite.

## Required tests

- Eligible tests are exported.
- Ineligible tests are excluded.
- Unknown requirement link prevents export.
- Rejected requirement link prevents export.
- Conflicting requirement link prevents export.
- Missing source refs prevents export.
- Golden fixture for executor export output.

## Golden fixtures

Useful. Include expected executor JSON output.

## Non-goals

Must not implement:

- test validation
- coverage calculation
- review report generation
- runtime skill calls
- executor execution

## Definition of done

- Export package includes only eligible validated tests.
- Tests prove exclusion rules and output shape.
- No tests are executed against a chatbot target.
