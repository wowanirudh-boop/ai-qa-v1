# C07 Requirement Extraction

## Purpose

Own converting `SourcePackage` into `CandidateRequirementPackage` through the Skill Runtime.

## Inputs

- `SourcePackage`
- Requirement extraction `SkillDefinition`

Input artifact path conventions:

- `artifacts/{project_id}/{run_id}/02_source_package/source_package.json`

## Outputs

- `CandidateRequirementPackage`
- Updated `SourcePackage` when extraction-related chunk statuses are written.
- `SkillRunRecord`

Output artifact path conventions:

- `artifacts/{project_id}/{run_id}/03_candidate_requirements/candidate_requirement_package.json`
- `artifacts/{project_id}/{run_id}/03_candidate_requirements/source_package_extraction_status.json` when an updated `SourcePackage` is emitted.
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

## Deterministic code responsibilities

- Select chunks eligible for extraction.
- Invoke the extraction skill through Skill Runtime.
- Validate every candidate requirement.
- Preserve `source_refs`.
- May set extraction-related `SourceChunk.processing_status` values such as `requirements_extracted`, `non_testable_context`, `out_of_scope`, `unclear`, or `failed_processing` based on extraction results.
- Write any updated `SourcePackage` as a new versioned artifact through the Artifact Store.

## Validation rules

- Each candidate must have non-empty `source_refs`.
- Candidate confidence must be between 0 and 1.
- Candidates must reference known source chunks.
- Updated source packages must preserve source chunk IDs, document IDs, text, and checksums.
- This component must not mutate source artifacts in place.
- This component must not emit `AtomicRequirement` records.

## Required tests

- Happy path extraction using fake skill runtime.
- Candidate missing `source_refs` is rejected.
- Unknown chunk reference fails.
- Confidence range validation.
- Updated source package is written as a new artifact when chunk statuses change.
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
- When extraction changes chunk processing statuses, the updated source package is written to the documented output path.
- Tests prove source traceability is preserved.
- Tests prove C07 does not atomize, govern, deduplicate, plan obligations, or generate tests.
- No final requirements or tests are produced.
