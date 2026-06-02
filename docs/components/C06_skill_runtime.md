# C06 Skill Runtime

## Purpose

Own loading `SkillDefinition`, executing runtime skills, validating skill inputs and outputs, and recording `SkillRunRecord`.

## Inputs

- Skill definition files.
- Input artifact paths.
- Expected input and output contract names.

Input artifact path conventions:

- Skill definitions live under `skills/`.
- Skill inputs are artifacts under `artifacts/{project_id}/{run_id}/...`.

## Outputs

- Skill output artifacts.
- Skill run records.

Output artifact path conventions:

- Component-specific output artifacts stay in their owning stage paths.
- Skill run records may be written to `artifacts/{project_id}/{run_id}/skill_runs/{skill_run_id}.json`.

## Data contracts used

- `SkillDefinition`
- `SkillRunRecord`
- Any input or output contract declared by the skill definition.

## Files/modules to create

May create:

- `src/ai_testgen/skill_runtime.py`
- `tests/unit/test_skill_runtime.py`
- `tests/unit/fixtures/golden/skill_runtime/`
- sample local fake skill definitions under `tests/unit/fixtures/`

## CLI command

Optional later: `ai-testgen skills run --skill-id <skill_id> --input <artifact_path> --output <artifact_path>`

## Runtime skills used

This component executes runtime skills. It should test with local fake skills only.

## Execution adapters

Supported adapter categories:

- `test_fake`: unit-test-only deterministic fake adapters injected directly by tests.
- `codex_cli`: intended v1 local/Codex production adapter. It executes `codex exec -` non-interactively, parses JSON output, and returns it to C06 for contract validation and artifact persistence.
- `future_provider_adapter`: optional later provider integration. Business components must not add provider SDK/API calls directly.

Adapter selection must be explicit through CLI options, environment configuration, or `ProjectConfig.metadata`.
If no adapter is configured, C06 must fail clearly rather than falling back to fake behavior.

## Deterministic code responsibilities

- Load and validate skill definitions.
- Validate input artifacts before skill execution.
- Execute a skill through a controlled adapter.
- Validate output artifacts after skill execution.
- Record `SkillRunRecord`.

## Validation rules

- A skill must declare input and output contracts.
- A skill run must record input and output artifact paths.
- Failed runs must record an error.
- No business component may bypass this runtime to call an LLM directly.

## Required tests

- Valid skill definition loads.
- Invalid skill definition fails.
- Fake skill execution succeeds.
- Failed fake skill records an error.
- Input and output contract validation occurs.

## Golden fixtures

Useful. Include a fake skill definition and expected run record.

## Non-goals

Must not implement:

- requirement extraction logic
- atomization logic
- test generation logic
- provider-specific external service calls for v1 tests
- business-specific prompt ownership

## Definition of done

- Runtime can execute fake skills with validated inputs and outputs.
- Skill run records are persisted and test-covered.
- No component-specific business logic is embedded in the runtime.
