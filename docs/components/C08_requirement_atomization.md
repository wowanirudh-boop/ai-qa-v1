# C08 Requirement Atomization

## Purpose

Own converting bounded `CandidateRequirement` work packets into an `AtomicRequirementLedger` through C06 Skill Runtime.

## Production mode

Skill-required in production.

C08 must use C06 Skill Runtime for requirement atomization and must not call an LLM directly.

## Inputs

- `CandidateRequirementPackage`
- Requirement atomization `SkillDefinition`

Input artifact path conventions:

- `artifacts/{project_id}/{run_id}/03_candidate_requirements/candidate_requirement_package.json`

## Outputs

- `AtomicRequirementLedger`
- `SkillRunRecord`

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

Requirement atomization skill through C06 Skill Runtime.

The default production skill definition is:

```text
skills/requirement_atomization_v1.json
```

C08 is skill-required in production. It must fail clearly if the required skill definition is missing or invalid, and it must not silently fall back to heuristic, regex-only, or sentence-splitting atomization.

## Deterministic code responsibilities

- Create bounded atomization work packets containing one `CandidateRequirement` or a small configured batch of `CandidateRequirement` records.
- Invoke atomization through C06 Skill Runtime.
- Validate skill output.
- Assign stable requirement IDs.
- Preserve candidate IDs.
- Preserve source references from candidates.
- Preserve or assign `origin` correctly for every atomic requirement.
- Validate every atomic requirement.

Deterministic atomization may exist only as an explicitly named test/dev helper. The orchestrator must not use deterministic atomization.

## Bounded work packet rule

C08 must process bounded work packets: one `CandidateRequirement` or a small configured batch of `CandidateRequirement` records per skill run.

If C08 uses `CandidateRequirementPackage` as the skill input contract, it must pass a bounded temporary package containing only the candidate or configured batch being processed. It must not pass an unbounded project-wide candidate package to a skill.

## Validation rules

- Every source-derived atomic requirement must preserve `source_refs`.
- Every source-derived atomic requirement must preserve the source candidate IDs in `candidate_ids`.
- Requirements with `origin` set to `inferred`, `assumption`, `user_added`, or `system_default` may lack `source_refs` only if approval before export is required.
- `status` must use the `AtomicRequirement` enum.
- `origin` must use the `AtomicRequirement.origin` enum and must not be confused with `status`.
- Atomization must not create obligations or test cases.
- Atomization must not perform governance, deduplication final decisions, obligation planning, or test generation.
- This component must not call an LLM directly.

## Required tests

- Happy path candidate to atomic requirement.
- Candidate split into multiple atomic requirements.
- Source references preserved.
- Candidate IDs preserved.
- Origin is preserved or assigned correctly.
- Missing source references rejected for source-derived validated requirements.
- Approval required for `inferred`, `assumption`, `user_added`, and `system_default` requirements lacking source refs.
- Production path requires the default atomization skill through C06 Skill Runtime.
- Missing or invalid production skill definition fails clearly instead of using heuristic atomization.
- Orchestrator-facing path does not use deterministic atomization.
- Golden fixture for candidate package to atomic ledger.

## Golden fixtures

Useful. Include a candidate with a compound statement and expected atomic requirements.

## Non-goals

Must not implement:

- governance decisions
- deduplication final merge behavior
- obligation planning
- test generation
- heuristic or regex-only production atomization
- direct LLM calls

## Definition of done

- Candidate packages become valid atomic requirement ledgers.
- Tests prove traceability is preserved.
- Tests prove `candidate_ids` and `source_refs` are preserved for source-derived atomic requirements.
- Tests prove production atomization requires C06 Skill Runtime and the default production skill definition.
- No governed ledger, obligations, or tests are produced.
