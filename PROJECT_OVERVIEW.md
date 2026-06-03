# AI Test Generation System — Project Overview

## Current Status

This project is building **v1 of an AI Test Generation System for chatbot testing**.

As of the latest project update, the component pipeline from **C00 through C15** has been built and reviewed. The latest C15 orchestrator review is treated as **PASS**, meaning the v1 component architecture is structurally complete and ready for end-to-end acceptance/demo testing.

Important context: there was an earlier C15 review failure around `resume=False` recording stale artifact paths. That issue was later fixed and re-reviewed successfully. Future chats should treat the post-fix C15 PASS as the current state unless a newer review says otherwise.

---

## Product Definition

The system is an **AI-assisted requirements-to-test compiler for chatbot systems**.

It ingests source material such as:

- bot flow diagrams,
- FAQ / KB documents,
- context documents,
- API references,
- policy documents,
- sample conversations,
- release notes,
- existing context or test assets,

and turns them into:

- source-backed candidate requirements,
- atomic requirements,
- governed requirements,
- test obligations,
- draft test cases,
- validated test suites,
- coverage reports,
- review reports,
- executor export packages.

The system is designed to generate test cases for a downstream **test executor system** that runs conversations against the deployed web chat link where the bot is available.

The core product goal is not simply “generate tests with an LLM.” The goal is to make test generation:

- traceable,
- reviewable,
- deterministic where possible,
- modular,
- schema-validated,
- resumable,
- safe from hallucinated scope,
- safe from missing scope where detectable.

---

## Core Philosophy

The central design philosophy is:

```text
Code orchestrates.
Skills reason.
Artifacts preserve state.
Schemas enforce contracts.
Reviews catch drift.
```

The system must not be a one-shot LLM prompt that reads all documents and writes tests.

Instead, the required flow is:

```text
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
```

This is the project’s most important architectural rule.

---

## Why Tests Cannot Come Directly From Raw Docs

Raw documents are often:

- ambiguous,
- incomplete,
- duplicated,
- contradictory,
- partially non-testable,
- outdated,
- too large for reliable LLM reasoning.

Generating tests directly from raw docs would make it hard to prove:

- why a test exists,
- which source supports it,
- whether scope was made up,
- whether scope was missed,
- whether a test is export-eligible,
- whether a requirement is conflicting or unresolved.

Therefore, test generation must flow through intermediate artifacts:

```text
Source evidence
→ Requirements
→ Obligations
→ Tests
```

A test without a requirement and obligation is an orphan and must not be exported.

---

## Code vs Runtime Skills

The project has a strict separation between deterministic code and LLM reasoning.

### Code owns

Deterministic code owns:

- orchestration,
- schema validation,
- artifact persistence,
- artifact paths,
- IDs,
- state,
- checksums,
- status transitions,
- deduplication workflow,
- coverage calculations,
- source/reference link validation,
- export eligibility,
- CLI behavior,
- retries and failure states,
- pipeline run state,
- test acceptance gates.

### Runtime skills own

Runtime skills own LLM reasoning tasks such as:

- interpreting source text,
- extracting candidate requirements,
- atomizing requirements,
- identifying ambiguity,
- identifying unsupported claims,
- drafting test conversations,
- drafting expected outcomes,
- drafting assertions,
- reviewing gaps,
- summarizing findings.

### Hard LLM rule

No business component may call an LLM provider directly.

All runtime skill execution must go through:

```text
C06 Skill Runtime
```

The intended call path is:

```text
Business component
→ C06 Skill Runtime
→ SkillDefinition
→ controlled adapter
→ validated skill output
→ artifact store
```

---

## Runtime Skill Expectations

Skills are product runtime assets, not Codex build prompts.

Runtime skill definitions live under:

```text
skills/
```

Expected core skills include:

```text
skills/requirement_extraction_v1.json
skills/requirement_atomization_v1.json
skills/test_case_writer_v1.json
skills/oracle_generator_v1.json
```

Optional / later reviewer skills may include:

```text
skills/unsupported_requirement_reviewer_v1.json
skills/atomicity_reviewer_v1.json
skills/conflict_reviewer_v1.json
skills/semantic_duplicate_reviewer_v1.json
skills/test_case_reviewer_v1.json
skills/gap_analyzer_v1.json
skills/review_summary_writer_v1.json
```

Every skill must declare:

- skill ID,
- version,
- purpose,
- input contract,
- output contract,
- grounding rules,
- JSON-only output behavior,
- source reference rules,
- uncertainty behavior,
- test/fake skill behavior.

---

## Artifact-Driven Architecture

The system uses local JSON artifacts as the persistent state between components.

Default artifact root:

```text
artifacts/{project_id}/{run_id}/
```

Canonical artifact flow:

```text
00_project_config/project_config.json
01_documents/documents.json
02_source_package/source_package.json
03_candidate_requirements/candidate_requirement_package.json
04_atomic_requirements/atomic_requirement_ledger.json
05_governed_requirements/governed_requirement_ledger.json
06_test_obligations/test_obligation_ledger.json
07_draft_tests/draft_test_suite.json
08_validated_tests/validated_test_suite.json
08_validated_tests/coverage_report.json
09_review_report/review_report.md
09_review_report/review_report_metadata.json
10_executor_export/tests.json
10_executor_export/executor_export_package.json
pipeline_run_state.json
```

Artifacts make the system:

- inspectable,
- repeatable,
- debuggable,
- resumable,
- testable component-by-component.

---

## Traceability Chain

The required traceability chain is:

```text
SourceChunk
→ CandidateRequirement
→ AtomicRequirement
→ GovernedRequirement
→ TestObligation
→ TestCase
→ ExecutorExportPackage
```

Key rules:

- Every source-derived candidate requirement must have `source_refs`.
- Every source-derived atomic requirement must preserve `candidate_ids` and `source_refs`.
- Every governed requirement must have a controlled status.
- Every test obligation must link to a governed requirement.
- Every test case must link to known `requirement_ids` and `obligation_ids`.
- Exportable tests must preserve source references.
- Unknown requirement IDs are rejected.
- Unknown obligation IDs are rejected.
- Rejected requirements cannot generate normal obligations.
- Conflicting requirements cannot generate normal exportable tests.
- Inferred / assumption / user-added / system-default requirements require approval before export unless policy explicitly says otherwise.

---

## Main Data Contracts

The canonical v1 contracts are:

```text
ProjectConfig
Document
SourceRef
SourceChunk
SourcePackage
CandidateRequirement
CandidateRequirementPackage
AtomicRequirement
AtomicRequirementLedger
GovernedRequirementLedger
TestObligation
TestObligationLedger
ConversationTurn
Assertion
TestCase
DraftTestSuite
ValidatedTestSuite
CoverageReport
ReviewReportMetadata
ExecutorExportPackage
SkillDefinition
SkillRunRecord
PipelineRunState
```

These are owned by **C01 Shared Schemas**.

The project should avoid undocumented dictionaries. Components should pass validated schema objects or artifact paths.

---

## Component Map

### C00 — Bootstrap and Architecture Docs

Purpose: create permanent project documentation and scaffolding.

Mode: docs-only / code-only.

Owns:

- `AGENTS.md`
- `README.md`
- `docs/*.md`
- `docs/components/*.md`
- initial source/test/example/skills directories.

Does not implement runtime behavior.

---

### C01 — Shared Schemas

Purpose: define and validate all canonical v1 data contracts.

Mode: code-only.

Owns:

- `src/ai_testgen/schemas.py`
- schema models,
- enums,
- contract validation,
- required field enforcement,
- traceability field enforcement.

Must not own artifact persistence or pipeline logic.

---

### C02 — Artifact Store

Purpose: own local JSON artifact read/write, stable paths, versioning, checksums, and path safety.

Mode: code-only.

Owns:

- `src/ai_testgen/artifact_store.py`
- artifact path construction,
- stable JSON writes,
- model loading,
- versioned writes,
- run-root helpers,
- path traversal protection.

Must not interpret business semantics.

---

### C03 — Project Configuration

Purpose: load, validate, and persist `ProjectConfig`.

Mode: code-only.

Produces:

```text
00_project_config/project_config.json
```

Must not ingest documents or create downstream artifacts.

---

### C04 — Document Ingestion

Purpose: read configured source files and create `Document` records.

Mode: code-only.

Produces:

```text
01_documents/documents.json
```

Must not chunk, classify semantically, extract requirements, or call runtime skills.

---

### C05 — Source Ledger

Purpose: split documents into stable `SourceChunk` records and create a `SourcePackage`.

Mode: code-only.

Produces:

```text
02_source_package/source_package.json
```

Must not extract requirements or classify content semantically using LLMs.

---

### C06 — Skill Runtime

Purpose: load and execute runtime skills, validate inputs/outputs, and record skill runs.

Mode: skill infrastructure.

Owns:

- `SkillDefinition` loading,
- fake/local skill execution for tests,
- input artifact validation,
- output artifact validation,
- `SkillRunRecord` persistence.

Important: C06 is the only allowed runtime skill execution boundary.

---

### C07 — Requirement Extraction

Purpose: convert `SourcePackage` into `CandidateRequirementPackage` through Skill Runtime.

Mode: skill-required.

Consumes:

```text
02_source_package/source_package.json
```

Produces:

```text
03_candidate_requirements/candidate_requirement_package.json
03_candidate_requirements/source_package_extraction_status.json
skill_runs/{skill_run_id}.json
```

Must:

- call C06 Skill Runtime,
- use bounded source chunk work packets,
- preserve source refs,
- validate candidates against source chunks,
- deterministically rewrite candidate IDs,
- account for source chunk processing statuses.

Must not atomize, govern, plan obligations, or generate tests.

---

### C08 — Requirement Atomization

Purpose: convert candidate requirements into atomic requirements through Skill Runtime.

Mode: skill-required.

Consumes:

```text
03_candidate_requirements/candidate_requirement_package.json
```

Produces:

```text
04_atomic_requirements/atomic_requirement_ledger.json
skill_runs/{skill_run_id}.json
```

Must:

- call C06 Skill Runtime in production,
- use `skills/requirement_atomization_v1.json`,
- preserve candidate IDs and source refs,
- validate all atomic requirements against candidates,
- deterministically rewrite requirement IDs.

Must not silently fall back to regex/heuristic atomization in production.

A deterministic atomization helper may exist only as an explicit test/dev helper.

---

### C09 — Requirement Governance

Purpose: convert atomic requirements into governed requirements.

Mode: hybrid.

Consumes:

```text
04_atomic_requirements/atomic_requirement_ledger.json
```

Produces:

```text
05_governed_requirements/governed_requirement_ledger.json
```

Owns:

- controlled requirement statuses,
- validation,
- conflict marking,
- duplicate handling,
- approval-required marking,
- rejection reasons,
- traceability preservation.

Reviewer skills may suggest findings, but deterministic code owns final statuses.

---

### C10 — Test Obligation Planning

Purpose: convert governed requirements into deterministic test obligations.

Mode: mostly code.

Consumes:

```text
05_governed_requirements/governed_requirement_ledger.json
ProjectConfig.coverage_policy
```

Produces:

```text
06_test_obligations/test_obligation_ledger.json
```

Owns deterministic obligation rules such as:

- entity collection → missing/provided/invalid entity obligations,
- business rule → positive/negative/boundary obligations,
- FAQ answer → direct/paraphrase/adjacent-topic obligations,
- API behavior → success/error obligations where documented.

Must not write test conversations or assertions.

---

### C11 — Test Case Generation

Purpose: generate draft test cases from obligations and linked governed requirements.

Mode: skill-required.

Consumes:

```text
06_test_obligations/test_obligation_ledger.json
05_governed_requirements/governed_requirement_ledger.json
ProjectConfig
executor context / policy where available
```

Produces:

```text
07_draft_tests/draft_test_suite.json
skill_runs/{skill_run_id}.json
```

Must:

- call C06 Skill Runtime,
- use bounded obligation work packets,
- preserve requirement IDs,
- preserve obligation IDs,
- preserve source refs,
- generate only draft tests.

Must not validate final export eligibility or write executor export artifacts.

---

### C12 — Test Validation and Coverage

Purpose: validate draft tests and compute coverage.

Mode: mostly code.

Consumes:

```text
07_draft_tests/draft_test_suite.json
05_governed_requirements/governed_requirement_ledger.json
06_test_obligations/test_obligation_ledger.json
optional 02_source_package/source_package.json
```

Produces:

```text
08_validated_tests/validated_test_suite.json
08_validated_tests/coverage_report.json
```

Owns:

- orphan test rejection,
- unknown requirement rejection,
- unknown obligation rejection,
- source ref matching,
- duplicate detection,
- export eligibility marking,
- coverage counting.

Must not draft tests, generate review reports, or export to executor.

---

### C13 — Review Report

Purpose: generate PM/QA-readable review artifacts from validated outputs.

Mode: mostly code.

Consumes:

```text
05_governed_requirements/governed_requirement_ledger.json
06_test_obligations/test_obligation_ledger.json
08_validated_tests/validated_test_suite.json
08_validated_tests/coverage_report.json
```

Produces:

```text
09_review_report/review_report.md
09_review_report/review_report_metadata.json
```

Owns:

- coverage summary,
- unresolved conflicts,
- blocked obligations,
- rejected tests,
- non-exportable tests,
- PM-facing reporting.

C13 intentionally relies on C12 for full validation and must not re-run C12 validation logic.

---

### C14 — Executor Export

Purpose: export approved/export-eligible tests to the executor package.

Mode: code-only.

Consumes:

```text
00_project_config/project_config.json
05_governed_requirements/governed_requirement_ledger.json
06_test_obligations/test_obligation_ledger.json
08_validated_tests/validated_test_suite.json
```

Produces:

```text
10_executor_export/tests.json
10_executor_export/executor_export_package.json
```

Owns:

- final export filtering,
- executor package metadata,
- preservation of test IDs, requirement IDs, obligation IDs, and source refs,
- final export gate.

Must not execute browser tests or call external executor services.

---

### C15 — End-to-End Orchestrator

Purpose: run the existing components in order, manage pipeline state, checkpoints, resume behavior, and CLI orchestration.

Mode: code-only orchestration.

Owns:

- stage ordering,
- component runner delegation,
- artifact path handoff,
- `pipeline_run_state.json`,
- resume/checkpoint behavior,
- `include_review` / `include_export`,
- failure reporting.

Must not implement C03-C14 business logic itself.

Important post-fix rule:

```text
When resume=False reruns a stage, PipelineRunState must record the newly produced artifact paths, not stale checkpoint paths.
```

Latest status: C15 was fixed and re-reviewed as PASS according to the latest project update.

---

## Current Build / Review Status

Current assumed status:

```text
C00 — built
C01 — built
C02 — built
C03 — built
C04 — built
C05 — built
C06 — built
C07 — built and tightened
C08 — built and corrected to be skill-required in production
C09 — built and aligned after guardrail update
C10 — built; review PASS WITH WARNINGS, no blockers
C11 — built
C12 — built; review PASS WITH WARNINGS, minor warnings addressed or accepted
C13 — built; review PASS WITH WARNINGS, no blockers
C14 — built; review PASS WITH WARNINGS, no blockers
C15 — built, initially failed on resume=False artifact handling, then fixed and latest review PASS
```

The project is ready for:

```text
end-to-end acceptance/demo testing
```

unless a newer review report says otherwise.

---

## Known Historical Issues and Resolutions

### C08 atomization drift

Earlier C08 implementation allowed heuristic atomization when no skill definition was supplied.

Resolution:

- C08 was changed to be skill-required in production.
- `skills/requirement_atomization_v1.json` is the expected production skill definition.
- Deterministic atomization, if retained, must be explicitly test/dev only.

### C12 ProjectConfig documentation mismatch

Earlier broad docs mentioned `ProjectConfig` as a C12 input while the C12 component spec did not require it.

Resolution / current stance:

- C12 v1 validates draft tests using ledgers and optional source package.
- `ProjectConfig` should not be treated as a required C12 input unless the component spec and data contracts explicitly define it.

### C13 review path drift

Earlier broad docs used an older C13 path:

```text
09_review/review_report.json
```

Current C13 output path is:

```text
09_review_report/review_report.md
09_review_report/review_report_metadata.json
```

### C14 executor contract

C14 currently emits a golden-tested executor `tests.json`.

Current stance:

- Do not over-formalize the executor contract until the real executor compatibility rules are known.
- C14 must preserve IDs and traceability in exported records.

### C15 resume=False bug

Earlier C15 reran stages on `resume=False` but recorded stale canonical artifact paths.

Resolution:

- C15 was fixed so returned runner artifact paths are validated and recorded.
- A regression test should exist proving newly produced artifacts are recorded, not stale v1 paths.
- Latest C15 review is treated as PASS.

---

## Review Practice

After each component build, use a post-build review prompt before moving on.

The review should check:

- component boundary,
- architecture alignment,
- data contract compliance,
- artifact behavior,
- traceability,
- runtime skill usage,
- tests and TDD,
- drift risks.

Review outcomes:

```text
PASS
PASS WITH WARNINGS
FAIL
```

Operating rule:

```text
PASS → proceed.
PASS WITH WARNINGS and Required fixes = None → proceed or do small cleanup.
FAIL → fix before proceeding.
```

---

## Future Chat Operating Model

Future Codex chats should use the repo as memory.

The standard instruction pattern is:

```text
Read:
AGENTS.md
docs/ARCHITECTURE.md
docs/COMPONENTS.md
docs/DATA_CONTRACTS.md
docs/TDD_RULES.md
docs/PIPELINE.md
docs/CODEX_WORKFLOW.md
relevant docs/components/CXX_*.md
relevant src/ai_testgen/*.py
relevant tests/unit/test_*.py

Work only on the requested task.
Do not broaden scope.
Do not implement future components.
Do not call LLMs directly.
Do not bypass schemas.
Use ArtifactStore for artifacts.
Use SkillRuntime for runtime skills.
Run targeted tests and full unit tests where practical.
Summarize files changed, tests changed, commands run, assumptions, and non-goals.
```

---

## Guardrails for Future Work

Future chats must not:

- generate tests directly from raw documents,
- bypass `AtomicRequirement` and `TestObligation`,
- accept orphan tests,
- export tests with unknown requirement IDs,
- export tests with unknown obligation IDs,
- export tests linked to conflicting/rejected requirements,
- call LLMs directly outside C06 Skill Runtime,
- add provider SDK calls inside business components,
- let skill outputs write final state without code validation,
- treat heuristic requirement atomization as production behavior,
- mutate prior artifacts in place,
- ignore returned runner artifact paths,
- silently reuse stale checkpoint artifacts,
- broaden component scope without explicit instruction.

---

## Near-Term Next Phase: End-to-End Acceptance / Demo Testing

The next major phase should validate the system as a whole with a small demo project.

Recommended acceptance test goals:

1. Create a small demo chatbot documentation set.
2. Run the full pipeline from config through executor export.
3. Verify every expected artifact is produced.
4. Verify source chunks become candidate requirements.
5. Verify candidate requirements become atomic requirements.
6. Verify governed requirements produce obligations.
7. Verify obligations produce draft tests.
8. Verify draft tests are validated.
9. Verify coverage report is accurate enough.
10. Verify review report is useful to a PM/QA reviewer.
11. Verify executor export contains only export-eligible tests.
12. Verify no direct raw-doc-to-test shortcut exists.
13. Verify resume behavior works.
14. Verify skip-review and skip-export behavior works.
15. Verify failure modes are clear.

Acceptance should include at least one happy path and at least one blocked/conflicting/invalid path.

---

## Recommended Next Documentation Files

Consider adding or updating these files:

```text
docs/PROJECT_OVERVIEW.md
docs/ACCEPTANCE_TEST_PLAN.md
docs/DEMO_PROJECT_GUIDE.md
docs/SKILL_AUTHORING_GUIDE.md
docs/EXECUTOR_CONTRACT_NOTES.md
```

`docs/PROJECT_OVERVIEW.md` should be this file.

---

## One-Sentence Summary for Future Chats

This project is a modular, artifact-driven, schema-validated AI test generation system for chatbot testing; it compiles source docs into source-backed requirements, requirements into obligations, obligations into tests, validates and reviews them, and exports only traceable tests, with code controlling orchestration and LLM reasoning allowed only through the Skill Runtime.
