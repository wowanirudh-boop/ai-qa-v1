# C10 Test Obligation Planning

## Purpose

Own converting `GovernedRequirementLedger` into `TestObligationLedger`.

## Inputs

- `GovernedRequirementLedger`
- `ProjectConfig.coverage_policy`

Input artifact path conventions:

- `artifacts/{project_id}/{run_id}/05_governed_requirements/governed_requirement_ledger.json`
- `artifacts/{project_id}/{run_id}/00_project_config/project_config.json`

## Outputs

- `TestObligationLedger`

Output artifact path conventions:

- `artifacts/{project_id}/{run_id}/06_test_obligations/test_obligation_ledger.json`

## Data contracts used

- `ProjectConfig`
- `AtomicRequirement`
- `GovernedRequirementLedger`
- `TestObligation`
- `TestObligationLedger`

## Files/modules to create

May create:

- `src/ai_testgen/obligation_planning.py`
- `tests/unit/test_obligation_planning.py`
- `tests/unit/fixtures/golden/obligation_planning/`

## CLI command

`ai-testgen plan-obligations --governed-ledger artifacts/{project_id}/{run_id}/05_governed_requirements/governed_requirement_ledger.json`

## Runtime skills used

None.

## Deterministic code responsibilities

- Create obligations from governed requirements according to coverage policy.
- Assign stable obligation IDs.
- Inherit source references from requirements.
- Mark blocked or skipped obligations where policy requires.

## Validation rules

- Must not generate full test cases.
- Must not create obligations from rejected requirements.
- Must not create normal exportable obligations from conflicting requirements.
- Every obligation must reference a known governed requirement.
- Every source-derived obligation must inherit `source_refs`.

## Required tests

- Happy path obligation planning.
- Rejected requirement creates no obligation.
- Conflicting requirement creates no normal exportable obligation.
- Obligation inherits source refs.
- Coverage policy affects obligation type.
- Golden fixture for governed ledger to obligation ledger.

## Golden fixtures

Useful. Include validated, rejected, and conflicting requirements.

## Non-goals

Must not implement:

- test case drafting
- runtime skill calls
- coverage report generation
- export package creation

## Definition of done

- Governed requirements become a valid obligation ledger.
- Tests prove rejected and conflicting requirements are handled correctly.
- No draft tests are produced.

