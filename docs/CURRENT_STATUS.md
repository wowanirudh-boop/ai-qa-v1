# AI Test Generation System — Current Status

Date: 2026-06-02

## Current State

The project is v1 of an AI-assisted requirements-to-test compiler for chatbot testing.

The core architecture is:

Source Document
→ Source Chunk
→ Candidate Requirement
→ Atomic Requirement
→ Governed Requirement
→ Test Obligation
→ Draft Test Case
→ Validated Test Suite
→ Review Report
→ Executor Export Package

Core philosophy:

Code orchestrates.
Skills reason.
Artifacts preserve state.
Schemas enforce contracts.
Reviews catch drift.

No business component may call an LLM directly.
All runtime skill execution must go through C06 Skill Runtime.

## Current Runtime Model

The intended v1 local runtime path is:

Business component
→ C06 SkillRuntime
→ SkillDefinition
→ codex_cli adapter
→ Codex CLI performs skill reasoning
→ C06 validates structured JSON output
→ ArtifactStore writes artifacts
→ SkillRunRecord records execution metadata

No OpenAI/Anthropic/provider SDK was added inside C07/C08/C11.

## Latest Implemented Fixes

The focused cleanup has been implemented.

Changed behavior:

- C06 SkillRunRecords now record safe adapter metadata.
- codex_cli adapter exposes:
  - adapter_name
  - adapter_mode
  - safe command identifier
  - exit_code
  - timeout_seconds
- C07 CandidateRequirementPackage now records skill_run_ids.
- C08 AtomicRequirementLedger now records skill_run_ids.
- C08 now batches candidates and calls C06 once per batch.
- C08 validates and merges batched outputs.
- CLI now exposes:
  - C08 --max-candidates-per-skill-run
  - C11 --max-obligations-per-skill-run
- C07, C08, and C11 all route through create_skill_runtime_for_run.
- local_fake is absent from normal runtime paths.
- Test fakes remain test-only.
- No provider SDK/API integration was added.
- C07/C08/C11 do not call Codex directly.

## Latest Tests

Commands run:

python -m pytest tests/unit/test_skill_runtime.py tests/unit/test_requirement_extraction.py tests/unit/test_requirement_atomization.py tests/unit/test_test_generation.py -q
Result: 93 passed

python -m pytest tests/unit -q
Result: 327 passed

## Latest Live Acceptance

Initial run with plain codex failed because the WindowsApps shim was not executable from subprocess.
This is expected environment behavior.
C06 correctly recorded a failed SkillRunRecord with adapter_name=codex_cli.

Successful fresh live C15 run used:

$env:PYTHONPATH='src'
$env:AI_TESTGEN_CODEX_CLI_COMMAND='C:\Users\Anirudh\AppData\Local\OpenAI\Codex\bin\716dda49c14d31a0\codex.exe'
python -m ai_testgen.cli run --config C:\Users\Anirudh\AppData\Local\Temp\ai_testgen_cleanup_live\project_config.json --run-id cleanup_live_002 --artifact-root artifacts --skill-adapter codex_cli

Artifact root:

artifacts/appointment_cleanup_live/cleanup_live_002

Acceptance counts:

- Candidates: 6
- Atomic requirements: 6
- Obligations: 6
- Draft tests: 6
- Validated tests: 6
- Exported tests: 6

SkillRunRecords by skill:

- requirement_extraction_v1: 2
- requirement_atomization_v1: 2
- test_case_writer_v1: 6
- oracle_generator_v1: 6

Verification:

- Schema validation passed.
- Source refs and upstream IDs were valid.
- Every live SkillRunRecord has:
  - adapter_name=codex_cli
  - adapter_mode=cli
  - adapter_command=codex.exe
  - exit_code=0
  - timeout_seconds=300
- C08 used multiple bounded skill runs.
- C11 used bounded obligation packets.
- Outputs were non-dummy and source-grounded.
- No provider SDK/API integration was added.
- local_fake is not present in normal runtime paths.
- C07/C08/C11 do not call Codex directly.

## Current Verdict

Architecture: PASS
C06 codex_cli runtime path: PASS
C07/C08/C11 shared resolver wiring: PASS
C08 bounded execution: PASS
C07/C08 skill_run_ids: PASS
SkillRunRecord adapter metadata: PASS
Fresh tiny C15 live run: PASS
Large order-tracking clean full rerun: not yet repeated after latest cleanup
Overall status: PASS WITH SMALL WARNINGS

## Current Warnings / Follow-ups

1. Full C15 still uses C11’s component default batch size.
2. The latest fresh full C15 acceptance used a small appointment-booking fixture.
3. A larger clean full acceptance should be run later on the order-tracking fixture with a new run_id.
4. The Windows PATH codex shim is not usable from subprocess, so AI_TESTGEN_CODEX_CLI_COMMAND should be set to the actual codex.exe path.
5. oracle_generator_v1 is used in the C11/full pipeline path; keep docs/tests clear about this.
6. Next phase should focus on demo hardening, report quality, executor compatibility, failure-mode testing, and larger acceptance fixtures.

## Important Guardrails

Future work must not:

- generate tests directly from raw documents;
- bypass AtomicRequirement or TestObligation;
- accept orphan tests;
- export tests with unknown requirement IDs;
- export tests with unknown obligation IDs;
- export tests linked to rejected/conflicting requirements;
- call LLMs directly outside C06 SkillRuntime;
- add provider SDK/API calls inside business components;
- let skills write final artifacts without code validation;
- reintroduce local_fake into normal runtime/config paths;
- silently reuse stale checkpoints;
- mutate prior artifacts in place.