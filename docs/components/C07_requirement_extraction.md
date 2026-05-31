# C07 Requirement Extraction

## Purpose

Own converting bounded `SourceChunk` work packets into `CandidateRequirementPackage` records through C06 Skill Runtime.

## Production mode

Skill-required in production.

C07 must use C06 Skill Runtime for requirement extraction and must not call an LLM directly.

## Inputs

- `SourcePackage`
- Requirement extraction `SkillDefinition`

Input artifact path conventions:

- `artifacts/{project_id}/{run_id}/02_source_package/source_package.json`

## Outputs

- `CandidateRequirementPackage`
- Source chunk extraction status artifact when extraction-related chunk statuses are written.
- `SkillRunRecord`

Output artifact path conventions:

- `artifacts/{project_id}/{run_id}/03_candidate_requirements/candidate_requirement_package.json`
- `artifacts/{project_id}/{run_id}/03_candidate_requirements/source_package_extraction_status.json` when extraction status accounting is emitted.
- `artifacts/{project_id}/{run_id}/skill_runs/{skill_run_id}.json`

## Data contracts used

- `SourcePackage`
- `SourceChunk`
- `SourceRef`
- `CandidateRequirement`
- `CandidateRequirementPackage`
- `SkillRunRecord`

## Files/modules to create

May create:

- `src/ai_testgen/requirement_extraction.py`
- `tests/unit/test_requirement_extraction.py`
- `tests/unit/fixtures/golden/requirement_extraction/`

## CLI command

`ai-testgen extract-requirements --source-package artifacts/{project_id}/{run_id}/02_source_package/source_package.json`

## Runtime skills used

Requirement extraction skill through C06 Skill Runtime.

C07 is skill-required in production. It must fail clearly if the required skill definition is missing or invalid, and it must not silently fall back to heuristic-only extraction.

## Deterministic code responsibilities

- Select chunks eligible for extraction.
- Create bounded extraction work packets containing one `SourceChunk` or a small configured batch of `SourceChunk` records.
- Invoke the extraction skill through C06 Skill Runtime.
- Validate every candidate requirement.
- Preserve `source_refs`.
- Account for every eligible chunk with an extraction status.
- Write the final `CandidateRequirementPackage` and extraction status artifacts through the Artifact Store.

## Bounded work packet rule

C07 must process bounded work packets: one `SourceChunk` or a small configured batch of `SourceChunk` records per skill run.

If C07 uses `SourcePackage` as the skill input contract, it must pass a bounded temporary `SourcePackage` containing only the chunk or configured batch being processed. It must not pass an unbounded project-wide `SourcePackage` to a skill.

## Source status rule

C07 should account for every eligible source chunk.

Before extraction, an eligible chunk may remain:

```text
not_processed
```

After extraction and source coverage accounting, each eligible chunk should eventually become one of:

```text
requirements_extracted
non_testable_context
duplicate
out_of_scope
unclear
failed_processing
```

If the current data contracts cannot represent per-chunk extraction results, `docs/DATA_CONTRACTS.md` and C01 schemas must be updated before C07 implementation.

## Validation rules

- Each candidate must have non-empty `source_refs`.
- Candidate confidence must be between 0 and 1.
- Candidates must reference known source chunks.
- Extraction status artifacts, including any updated `SourcePackage`, must preserve source chunk IDs, document IDs, text, and checksums.
- This component must not mutate source artifacts in place.
- This component must not emit `AtomicRequirement` records.
- This component must not call an LLM directly.

## Required tests

- Happy path extraction using fake skill runtime.
- Candidate missing `source_refs` is rejected.
- Unknown chunk reference fails.
- Confidence range validation.
- Extraction status artifact is written as a new artifact when chunk statuses change.
- Bounded work packets are passed to C06 Skill Runtime.
- Unbounded project-wide `SourcePackage` inputs are not passed to skills.
- Every eligible chunk is accounted for with an extraction status.
- Golden fixture from source package to candidate package.

## Golden fixtures

Useful. Include one source package and expected candidate package.

## Non-goals

Must not implement:

- atomization
- governance or deduplication
- final requirement status decisions
- test obligations
- test cases
- in-place artifact mutation
- direct LLM calls

## Definition of done

- Source package can become a valid candidate requirement package through Skill Runtime.
- When extraction changes chunk processing statuses, the extraction status artifact is written to the documented output path.
- Tests prove source traceability is preserved.
- Tests prove production extraction requires C06 Skill Runtime.
- Tests prove C07 does not atomize, govern, deduplicate, plan obligations, or generate tests.
- No final requirements or tests are produced.
