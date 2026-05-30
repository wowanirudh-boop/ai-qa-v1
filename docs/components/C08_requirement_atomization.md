# C08 Requirement Atomization

## Purpose

Own converting `CandidateRequirementPackage` into `AtomicRequirementLedger`.

## Inputs

- `CandidateRequirementPackage`
- Optional atomization `SkillDefinition`

Input artifact path conventions:

- `artifacts/{project_id}/{run_id}/03_candidate_requirements/candidate_requirement_package.json`

## Outputs

- `AtomicRequirementLedger`
- `SkillRunRecord` when a runtime skill is used.

Output artifact path conventions:

- `artifacts/{project_id}/{run_id}/04_atomic_requirements/atomic_requirement_ledger.json`
- `artifacts/{project_id}/{run_id}/skill_runs/{skill_run_id}.json`

## Data contracts used

- `CandidateRequirementPackage`
- `CandidateRequirement`
- `AtomicRequirement`
- `AtomicRequirementLedger`
- `SourceRef`
- `SkillRunRecord`

## Files/modules to create

May create:

- `src/ai_testgen/requirement_atomization.py`
- `tests/unit/test_requirement_atomization.py`
- `tests/unit/fixtures/golden/requirement_atomization/`

## CLI command

`ai-testgen atomize-requirements --candidates artifacts/{project_id}/{run_id}/03_candidate_requirements/candidate_requirement_package.json`

## Runtime skills used

Optional atomization skill through C06 Skill Runtime.

## Deterministic code responsibilities

- Convert candidate statements into one or more atomic requirements.
- Assign stable requirement IDs.
- Preserve candidate IDs.
- Preserve source references from candidates.
- Preserve or assign `origin` correctly for every atomic requirement.
- Validate every atomic requirement.

## Validation rules

- Every source-derived atomic requirement must preserve `source_refs`.
- Requirements with `origin` set to `inferred`, `assumption`, `user_added`, or `system_default` may lack `source_refs` only if approval before export is required.
- `status` must use the `AtomicRequirement` enum.
- `origin` must use the `AtomicRequirement.origin` enum and must not be confused with `status`.
- Atomization must not create obligations or test cases.

## Required tests

- Happy path candidate to atomic requirement.
- Candidate split into multiple atomic requirements.
- Source references preserved.
- Origin is preserved or assigned correctly.
- Missing source references rejected for source-derived validated requirements.
- Approval required for `inferred`, `assumption`, `user_added`, and `system_default` requirements lacking source refs.
- Golden fixture for candidate package to atomic ledger.

## Golden fixtures

Useful. Include a candidate with a compound statement and expected atomic requirements.

## Non-goals

Must not implement:

- governance decisions
- deduplication final merge behavior
- obligation planning
- test generation
- direct LLM calls

## Definition of done

- Candidate packages become valid atomic requirement ledgers.
- Tests prove traceability is preserved.
- No governed ledger, obligations, or tests are produced.
