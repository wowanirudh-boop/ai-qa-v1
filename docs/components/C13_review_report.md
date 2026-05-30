# C13 Review Report

## Purpose

Own creating a human-readable `ReviewReport` from governed requirements, obligations, validated tests, and coverage.

## Inputs

- `GovernedRequirementLedger`
- `TestObligationLedger`
- `ValidatedTestSuite`
- `CoverageReport`

Input artifact path conventions:

- `artifacts/{project_id}/{run_id}/05_governed_requirements/governed_requirement_ledger.json`
- `artifacts/{project_id}/{run_id}/06_test_obligations/test_obligation_ledger.json`
- `artifacts/{project_id}/{run_id}/08_validated_tests/validated_test_suite.json`
- `artifacts/{project_id}/{run_id}/08_validated_tests/coverage_report.json`

## Outputs

- Human-readable review report.
- `ReviewReportMetadata`.

Output artifact path conventions:

- `artifacts/{project_id}/{run_id}/09_review_report/review_report.md`
- `artifacts/{project_id}/{run_id}/09_review_report/review_report_metadata.json`

## Data contracts used

- `GovernedRequirementLedger`
- `TestObligationLedger`
- `ValidatedTestSuite`
- `CoverageReport`
- `ReviewReportMetadata`

## Files/modules to create

May create:

- `src/ai_testgen/review_report.py`
- `tests/unit/test_review_report.py`
- `tests/unit/fixtures/golden/review_report/`

## CLI command

`ai-testgen review-report --validated-suite artifacts/{project_id}/{run_id}/08_validated_tests/validated_test_suite.json`

## Runtime skills used

None.

## Deterministic code responsibilities

- Summarize requirement status.
- Summarize obligation status.
- Summarize validation and coverage.
- List rejected, blocked, or non-exportable items.
- Write review metadata.

## Validation rules

- Referenced artifacts must exist.
- Report generation must not change validation state.
- Report content should be deterministic for golden tests.

## Required tests

- Happy path report generation.
- Report includes coverage summary.
- Report includes rejected or blocked items.
- Metadata references expected artifacts.
- Input artifacts remain unchanged.
- Golden fixture for report markdown.

## Golden fixtures

Useful. Include expected `review_report.md` for a small validated suite.

## Non-goals

Must not implement:

- validation state changes
- coverage calculation
- executor export
- runtime skill calls

## Definition of done

- Review report and metadata are generated from existing artifacts.
- Tests prove deterministic output and no mutation of input state.

