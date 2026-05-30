# C09 Requirement Governance

## Purpose

Own status decisions, deduplication policy, conflict marking, approval gates, and `GovernedRequirementLedger`.

## Inputs

- `AtomicRequirementLedger`
- `ProjectConfig`
- Optional semantic comparison skill.

Input artifact path conventions:

- `artifacts/{project_id}/{run_id}/04_atomic_requirements/atomic_requirement_ledger.json`
- `artifacts/{project_id}/{run_id}/00_project_config/project_config.json`

## Outputs

- `GovernedRequirementLedger`
- `SkillRunRecord` when a semantic comparison skill is used.

Output artifact path conventions:

- `artifacts/{project_id}/{run_id}/05_governed_requirements/governed_requirement_ledger.json`
- `artifacts/{project_id}/{run_id}/skill_runs/{skill_run_id}.json`

## Data contracts used

- `ProjectConfig`
- `AtomicRequirement`
- `AtomicRequirementLedger`
- `GovernedRequirementLedger`
- `SkillRunRecord`

## Files/modules to create

May create:

- `src/ai_testgen/requirement_governance.py`
- `tests/unit/test_requirement_governance.py`
- `tests/unit/fixtures/golden/requirement_governance/`

## CLI command

`ai-testgen govern-requirements --atomic-ledger artifacts/{project_id}/{run_id}/04_atomic_requirements/atomic_requirement_ledger.json`

## Runtime skills used

Optional semantic similarity or comparison skill through C06 Skill Runtime only.

## Deterministic code responsibilities

- Apply status decisions.
- Own deduplication workflow, thresholds, IDs, state, and final merge behavior.
- Mark conflicts.
- Apply approval gates.
- Create governance summary counts.

## Validation rules

- Must not silently merge ambiguous, related, or conflicting requirements.
- Duplicates must identify `duplicate_of`.
- Conflicts should identify `conflicts_with`.
- Rejected requirements remain in the ledger for audit but cannot generate obligations.
- Source-derived validated requirements must have `source_refs`.

## Required tests

- Valid requirement becomes governed and validated.
- Duplicate is marked without silent deletion.
- Conflict is marked and preserved.
- Rejected requirement is retained but ineligible for obligations.
- Approval required for requirements with `origin` set to `inferred`, `assumption`, `user_added`, or `system_default` when they lack `source_refs`.
- Golden fixture for atomic ledger to governed ledger.

## Golden fixtures

Useful. Include duplicate and conflicting requirement examples.

## Non-goals

Must not implement:

- obligation generation
- test generation
- source chunking
- artifact store internals
- direct LLM calls

## Definition of done

- Atomic requirement ledgers become governed ledgers with explicit statuses.
- Tests prove deduplication, conflict, rejection, and approval-gate behavior.
- No obligations or tests are produced.
