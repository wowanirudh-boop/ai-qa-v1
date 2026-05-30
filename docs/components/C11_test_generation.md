# C11 Test Case Generation

## Purpose

Own generating `DraftTestSuite` from `TestObligationLedger` through the Skill Runtime.

## Inputs

- `TestObligationLedger`
- `GovernedRequirementLedger`
- Test generation `SkillDefinition`

Input artifact path conventions:

- `artifacts/{project_id}/{run_id}/06_test_obligations/test_obligation_ledger.json`
- `artifacts/{project_id}/{run_id}/05_governed_requirements/governed_requirement_ledger.json`

## Outputs

- `DraftTestSuite`
- `SkillRunRecord`

Output artifact path conventions:

- `artifacts/{project_id}/{run_id}/07_draft_tests/draft_test_suite.json`
- `artifacts/{project_id}/{run_id}/skill_runs/{skill_run_id}.json`

## Data contracts used

- `GovernedRequirementLedger`
- `TestObligation`
- `TestObligationLedger`
- `ConversationTurn`
- `Assertion`
- `TestCase`
- `DraftTestSuite`
- `SkillRunRecord`

## Files/modules to create

May create:

- `src/ai_testgen/test_generation.py`
- `tests/unit/test_test_generation.py`
- `tests/unit/fixtures/golden/test_generation/`

## CLI command

`ai-testgen generate-tests --obligations artifacts/{project_id}/{run_id}/06_test_obligations/test_obligation_ledger.json`

## Runtime skills used

Test generation skill through C06 Skill Runtime.

## Deterministic code responsibilities

- Prepare governed requirements and obligations for the runtime skill.
- Invoke Skill Runtime.
- Validate draft test cases.
- Ensure every test includes `requirement_ids` and `obligation_ids`.
- Preserve source references from obligations.

## Validation rules

- Must not generate test cases directly from raw documents or source chunks.
- Every `TestCase` must include non-empty `requirement_ids`.
- Every `TestCase` must include non-empty `obligation_ids`.
- Draft tests must reference known obligations and requirements from inputs.
- This component does not decide final export eligibility.

## Required tests

- Happy path draft suite generation using fake skill runtime.
- Missing `requirement_ids` fails.
- Missing `obligation_ids` fails.
- Unknown obligation reference fails.
- Source refs preserved from obligations.
- Golden fixture for obligation ledger to draft suite.

## Golden fixtures

Useful. Include one obligation ledger and expected draft suite.

## Non-goals

Must not implement:

- raw document to test generation
- validation coverage report
- executor export
- governance decisions
- direct LLM calls

## Definition of done

- Obligations can produce a valid draft test suite through Skill Runtime.
- Tests prove no orphan or raw-document-derived tests are emitted.
- No validated suite or export package is produced.

