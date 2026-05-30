# C12 Test Validation and Coverage

## Purpose

Own validating `DraftTestSuite` into `ValidatedTestSuite` and creating `CoverageReport`.

## Inputs

- `DraftTestSuite`
- `GovernedRequirementLedger`
- `TestObligationLedger`
- Optional `SourcePackage` for source chunk coverage.

Input artifact path conventions:

- `artifacts/{project_id}/{run_id}/07_draft_tests/draft_test_suite.json`
- `artifacts/{project_id}/{run_id}/05_governed_requirements/governed_requirement_ledger.json`
- `artifacts/{project_id}/{run_id}/06_test_obligations/test_obligation_ledger.json`
- `artifacts/{project_id}/{run_id}/02_source_package/source_package.json`

## Outputs

- `ValidatedTestSuite`
- `CoverageReport`

Output artifact path conventions:

- `artifacts/{project_id}/{run_id}/08_validated_tests/validated_test_suite.json`
- `artifacts/{project_id}/{run_id}/08_validated_tests/coverage_report.json`

## Data contracts used

- `DraftTestSuite`
- `ValidatedTestSuite`
- `CoverageReport`
- `TestCase`
- `GovernedRequirementLedger`
- `TestObligationLedger`
- `SourcePackage`

## Files/modules to create

May create:

- `src/ai_testgen/test_validation.py`
- `src/ai_testgen/coverage.py`
- `tests/unit/test_test_validation.py`
- `tests/unit/test_coverage.py`
- `tests/unit/fixtures/golden/test_validation_coverage/`

## CLI command

`ai-testgen validate-tests --draft-suite artifacts/{project_id}/{run_id}/07_draft_tests/draft_test_suite.json`

## Runtime skills used

None.

## Deterministic code responsibilities

- Reject orphan test cases.
- Validate requirement and obligation references.
- Enforce export eligibility rules.
- Produce validation summary.
- Produce coverage counts.

## Validation rules

- Test cases with unknown `requirement_ids` must be rejected.
- Test cases with unknown `obligation_ids` must be rejected.
- Test cases linked to conflicting requirements are not exportable.
- `source_refs` are required before tests can become `valid`, `approved`, `exported`, or exportable.
- Tests without `source_refs` must remain non-exportable or be rejected.
- Coverage counts must be zero or positive.

## Required tests

- Valid draft test becomes valid.
- Orphan test case is rejected.
- Unknown requirement ID is rejected.
- Unknown obligation ID is rejected.
- Conflicting requirement makes test not exportable.
- Missing `source_refs` prevent valid, approved, exported, and exportable status.
- Coverage counts are correct and non-negative.
- Golden fixture for draft suite to validated suite and coverage report.

## Golden fixtures

Useful. Include valid, orphan, and conflicting examples.

## Non-goals

Must not implement:

- draft test generation
- runtime skill calls
- human review report wording
- executor export files

## Definition of done

- Draft suites become validated suites with deterministic coverage reports.
- Tests prove orphan rejection and export eligibility behavior.
- No executor export package is created.
