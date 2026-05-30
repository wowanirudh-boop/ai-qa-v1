# C02 Artifact Store

## Purpose

Own local JSON artifact read/write, versioned paths, checksums, and artifact existence validation.

## Inputs

- Validated contract data from C01.
- Artifact root, project ID, run ID, stage path, and file name.

Input artifact path conventions:

- Reads from `artifacts/{project_id}/{run_id}/{stage}/{artifact_name}.json`.

## Outputs

- Persisted JSON artifacts.
- Loaded JSON artifacts.
- Checksums and existence validation results.

Output artifact path conventions:

- Writes to `artifacts/{project_id}/{run_id}/{stage}/{artifact_name}.json`.
- May write adjacent checksum metadata only if documented by tests.

## Data contracts used

- May store any canonical contract.
- Does not interpret business meaning of those contracts.

## Files/modules to create

May create:

- `src/ai_testgen/artifact_store.py`
- `tests/unit/test_artifact_store.py`
- `tests/unit/fixtures/golden/artifact_store/`

## CLI command

Optional later: `ai-testgen artifacts verify --root artifacts/{project_id}/{run_id}`.

## Runtime skills used

None.

## Deterministic code responsibilities

- Create artifact directories.
- Write stable JSON.
- Read JSON.
- Calculate checksums.
- Validate artifact existence.
- Prevent path traversal outside the configured artifact root.

## Validation rules

- Artifact paths must remain under the configured artifact root.
- JSON writes must be deterministic enough for golden tests.
- Missing artifacts must produce explicit errors.
- The store must not validate business rules beyond optional contract validator integration.

## Required tests

- Artifact write/read round trip.
- Missing artifact error.
- Checksum consistency.
- Path traversal rejection.
- Golden fixture test for stable JSON formatting.

## Golden fixtures

Useful. Include at least one small artifact write/read fixture.

## Non-goals

Must not implement:

- project configuration semantics
- requirement or test validation
- skill execution
- pipeline orchestration
- business-specific artifact transformations

## Definition of done

- Local JSON artifacts can be safely written, read, checksummed, and verified.
- Tests prove path safety and stable output.
- No requirement or test business logic is included.

