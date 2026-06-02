# Components

## Purpose

This file defines the v1 component map for the AI Test Generation System.

The system is built component by component. Each component has:

- a narrow purpose,
- explicit inputs,
- explicit outputs,
- explicit data contracts,
- explicit artifact paths,
- explicit runtime skill usage,
- tests,
- non-goals.

The system is a modular monolith, not a microservice system in v1.

## Shared Component Rules

Every component must follow these rules:

1. Implement only its own responsibility.
2. Read and write validated artifacts.
3. Use C01 schemas for validation.
4. Use C02 Artifact Store for artifact persistence.
5. Do not mutate prior artifacts in place.
6. Preserve traceability.
7. Do not call LLMs directly.
8. Use C06 Skill Runtime for runtime skills.
9. Do not generate downstream artifacts outside the component scope.
10. Do not implement future components.
11. Add unit tests.
12. Add golden fixtures where artifact transformation occurs.
13. Fail clearly on invalid inputs.

## Component Execution Modes

Each component has one production execution mode.

### Code-only

The component is deterministic and must not invoke runtime skills.

### Skill infrastructure

The component loads, validates, and executes skills. It may use fake/local skills in tests. It is the only boundary where provider adapters may eventually live.

### Skill-required

The component must use a runtime skill in production.

It may use fake skills in tests, but the production/default path must not silently fall back to heuristic-only behavior.

If the skill definition is missing or invalid, the component must fail clearly.

### Hybrid

The component uses deterministic code for final decisions, but may use runtime skills for review findings, semantic comparison, or content assistance.

LLM findings are suggestions. Code owns final statuses and persistence.

### Mostly code

The component is primarily deterministic, but may optionally call helper/reviewer skills later. Its core function must not depend on an LLM.

## Component Summary Table

| ID | Component | Production mode | Main input | Main output |
|---|---|---|---|---|
| C00 | Bootstrap and architecture docs | Code-only / docs-only | Bootstrap prompt | Repo docs and scaffolding |
| C01 | Shared schemas | Code-only | Data contract docs / dicts | Validated schema objects |
| C02 | Artifact store | Code-only | Validated artifacts | Persisted local JSON artifacts |
| C03 | Project configuration | Code-only | User project config | `ProjectConfig` artifact |
| C04 | Document ingestion | Code-only | `ProjectConfig`, source files | `Documents` artifact |
| C05 | Source ledger | Code-only | `Documents` | `SourcePackage` |
| C06 | Skill runtime | Skill infrastructure | Skill definitions, artifacts | Skill outputs, `SkillRunRecord` |
| C07 | Requirement extraction | Skill-required | `SourcePackage` | `CandidateRequirementPackage` |
| C08 | Requirement atomization | Skill-required | `CandidateRequirementPackage` | `AtomicRequirementLedger` |
| C09 | Requirement governance | Hybrid | `AtomicRequirementLedger` | `GovernedRequirementLedger` |
| C10 | Test obligation planning | Mostly code | `GovernedRequirementLedger` + `ProjectConfig.coverage_policy` | `TestObligationLedger` |
| C11 | Test case generation | Skill-required | `TestObligationLedger` + requirements | `DraftTestSuite` |
| C12 | Test validation and coverage | Mostly code | `DraftTestSuite` + ledgers | `ValidatedTestSuite`, `CoverageReport` |
| C13 | Review report | Mostly code | Validated artifacts and findings | Review report + `ReviewReportMetadata` |
| C14 | Executor export | Code-only | Approved validated suite | `ExecutorExportPackage` |
| C15 | End-to-end orchestrator | Code-only orchestration | Project/run inputs | Pipeline run artifacts |

## Build Order

Build components in this order:

1. C00 Bootstrap and architecture docs
2. C01 Shared schemas
3. C02 Artifact store
4. C03 Project configuration
5. C04 Document ingestion
6. C05 Source ledger
7. C06 Skill runtime
8. C07 Requirement extraction
9. C08 Requirement atomization
10. C09 Requirement governance
11. C10 Test obligation planning
12. C11 Test case generation
13. C12 Test validation and coverage
14. C13 Review report
15. C14 Executor export
16. C15 End-to-end orchestrator

Do not build later components early.

## C00 Bootstrap and Architecture Docs

### Purpose

Create permanent architecture documentation and repository scaffolding for v1.

### Production mode

Code-only / docs-only.

### Owns

- `AGENTS.md`
- `README.md`
- `docs/*.md`
- `docs/components/*.md`
- initial source tree
- initial test folders
- initial examples folder
- initial skills folder

### Must not own

- schemas implementation
- artifact store implementation
- CLI orchestration
- runtime skill execution
- requirement extraction
- atomization
- test generation
- export logic

### Done when

The repo has clear architecture docs, component specs, TDD rules, pipeline docs, and scaffolding.

## C01 Shared Schemas

### Purpose

Own canonical schema definitions and validation for every v1 data contract.

### Production mode

Code-only.

### Inputs

- JSON-like Python objects or dictionaries.
- Data contract definitions from `docs/DATA_CONTRACTS.md`.

### Outputs

- Validated contract objects.
- Validation errors.

### Owns

- required field validation,
- enum validation,
- numeric range validation,
- traceability field validation,
- local ID reference validation where context is supplied.

### Must not own

- artifact persistence,
- pipeline orchestration,
- runtime skill execution,
- requirement extraction,
- test generation.

### Important contracts

- `ProjectConfig`
- `Document`
- `SourceRef`
- `SourceChunk`
- `SourcePackage`
- `CandidateRequirement`
- `CandidateRequirementPackage`
- `AtomicRequirement`
- `AtomicRequirementLedger`
- `GovernedRequirementLedger`
- `TestObligation`
- `TestObligationLedger`
- `TestCase`
- `DraftTestSuite`
- `ValidatedTestSuite`
- `CoverageReport`
- `ReviewReportMetadata`
- `ExecutorExportPackage`
- `SkillDefinition`
- `SkillRunRecord`
- `PipelineRunState`

### Done when

All v1 contracts validate deterministically and tests cover required fields, enums, confidence ranges, statuses, and traceability rules.

## C02 Artifact Store

### Purpose

Own local JSON artifact read/write, versioned paths, checksums, and artifact existence validation.

### Production mode

Code-only.

### Inputs

- Validated contract data.
- Artifact root.
- Project ID.
- Run ID.
- Stage.
- Artifact name.

### Outputs

- Persisted JSON artifacts.
- Loaded JSON artifacts.
- Checksums.
- Existence validation.

### Owns

- stable JSON writes,
- JSON reads,
- checksum calculation,
- path safety,
- versioned paths,
- missing artifact errors.

### Must not own

- project configuration semantics,
- requirement semantics,
- test semantics,
- skill execution,
- pipeline orchestration.

### Done when

Artifacts can be safely written, read, checksummed, and verified under `artifacts/{project_id}/{run_id}/`.

## C03 Project Configuration

### Purpose

Own loading, validating, and saving `ProjectConfig`.

### Production mode

Code-only.

### Inputs

- User-authored project config JSON.
- Optional artifact root.
- Run ID.

### Outputs

- Validated `ProjectConfig`.
- Persisted project config artifact.

### Artifact output

```text
artifacts/{project_id}/{run_id}/00_project_config/project_config.json
```

### Owns

- required config field validation,
- conservative defaults,
- config save through Artifact Store,
- config CLI smoke command.

### Must not own

- document ingestion,
- source chunking,
- requirement extraction,
- runtime skills,
- test generation.

### Done when

Project config can be loaded, validated, and saved to the expected artifact path.

## C04 Document Ingestion

### Purpose

Own reading source documents and creating `Document` records.

### Production mode

Code-only.

### Inputs

- Validated `ProjectConfig`.
- Source files from configured `source_paths`.

### Outputs

- Document collection artifact.

### Artifact output

```text
artifacts/{project_id}/{run_id}/01_documents/documents.json
```

### Owns

- source file discovery,
- supported local text reads for v1,
- deterministic document IDs,
- document content checksums,
- ingestion statuses.

### Must not own

- source chunking,
- semantic classification,
- requirement extraction,
- runtime skills,
- test generation.

### Done when

Source files become valid `Document` records and tests prove checksums, required fields, duplicates, and error handling.

## C05 Source Ledger

### Purpose

Own chunking documents into `SourceChunk` records and creating a `SourcePackage`.

### Production mode

Code-only.

### Inputs

- Document collection artifact.
- Source document content referenced by each `Document`.

### Outputs

- `SourcePackage`.

### Artifact output

```text
artifacts/{project_id}/{run_id}/02_source_package/source_package.json
```

### Owns

- deterministic text chunking,
- stable chunk IDs,
- chunk checksums,
- initial `processing_status`,
- source package checksum,
- chunk-to-document traceability.

### Must not own

- requirement extraction,
- semantic classification,
- non-testable context classification using LLM reasoning,
- candidate requirements,
- runtime skills,
- test generation.

### Done when

Documents become deterministic source chunks and every chunk references a known document.

## C06 Skill Runtime

### Purpose

Own loading `SkillDefinition`, executing runtime skills, validating skill inputs and outputs, and recording `SkillRunRecord`.

### Production mode

Skill infrastructure.

### Inputs

- Skill definition files under `skills/`.
- Input artifact paths.
- Expected input and output contracts.

### Outputs

- Skill output artifacts.
- `SkillRunRecord`.

### Skill run artifact output

```text
artifacts/{project_id}/{run_id}/skill_runs/{skill_run_id}.json
```

### Owns

- skill definition loading,
- skill definition validation,
- input artifact validation,
- controlled skill adapter execution,
- output artifact validation,
- skill run records,
- fake/local skill support for tests.

### Must not own

- requirement extraction logic,
- atomization logic,
- test generation logic,
- business-specific prompt ownership,
- business-specific artifact transformations.

### Important rule

C06 is the only allowed boundary for runtime skill execution. No business component may call an LLM directly.

### Adapter types

- `test_fake`: unit-test-only deterministic fake adapters injected by tests.
- `codex_cli`: intended v1 local/Codex production adapter using non-interactive Codex CLI execution.
- `future_provider_adapter`: optional later provider integration; not required for v1 and not owned by business components.

### Done when

The runtime can execute fake skills with validated inputs and outputs, and skill runs are persisted and test-covered.

## C07 Requirement Extraction

### Purpose

Own converting `SourcePackage` into `CandidateRequirementPackage` through C06 Skill Runtime.

### Production mode

Skill-required.

### Inputs

- `SourcePackage`
- requirement extraction `SkillDefinition`

### Outputs

- `CandidateRequirementPackage`
- updated source extraction status artifact when chunk statuses change
- `SkillRunRecord`

### Artifact inputs

```text
artifacts/{project_id}/{run_id}/02_source_package/source_package.json
```

### Artifact outputs

```text
artifacts/{project_id}/{run_id}/03_candidate_requirements/candidate_requirement_package.json
artifacts/{project_id}/{run_id}/03_candidate_requirements/source_package_extraction_status.json
artifacts/{project_id}/{run_id}/skill_runs/{skill_run_id}.json
```

### Required runtime skill

```text
skills/requirement_extraction_v1.json
```

### Owns

- selecting chunks eligible for extraction,
- creating bounded extraction work packets,
- invoking requirement extraction through Skill Runtime,
- validating every candidate requirement,
- preserving source references,
- rewriting candidate IDs deterministically,
- merging per-chunk or per-batch skill outputs,
- writing final candidate package,
- writing updated source status package when statuses change.

### Bounded work packet rule

C07 must not pass an unbounded large source corpus to a skill.

It should process one chunk or a small configured batch of chunks per skill run.

If C07 uses `SourcePackage` as the skill input contract, it must pass a bounded temporary `SourcePackage` containing only the chunk or batch being processed.

### Source status rule

C07 should account for every eligible source chunk.

Each eligible chunk should eventually become one of:

```text
requirements_extracted
non_testable_context
duplicate
out_of_scope
unclear
failed_processing
```

If the current data contracts cannot represent per-chunk extraction results, update `docs/DATA_CONTRACTS.md` and C01 schemas to add a controlled chunk-level extraction result field.

### Must not own

- atomization,
- requirement governance,
- deduplication final decisions,
- final requirement status decisions,
- test obligations,
- test cases,
- direct LLM calls.

### Done when

A source package can become a valid candidate requirement package through Skill Runtime, with traceability preserved and source chunk status accounting supported.

## C08 Requirement Atomization

### Purpose

Own converting `CandidateRequirementPackage` into `AtomicRequirementLedger` through C06 Skill Runtime.

### Production mode

Skill-required.

### Inputs

- `CandidateRequirementPackage`
- requirement atomization `SkillDefinition`

### Outputs

- `AtomicRequirementLedger`
- `SkillRunRecord`

### Artifact input

```text
artifacts/{project_id}/{run_id}/03_candidate_requirements/candidate_requirement_package.json
```

### Artifact outputs

```text
artifacts/{project_id}/{run_id}/04_atomic_requirements/atomic_requirement_ledger.json
artifacts/{project_id}/{run_id}/skill_runs/{skill_run_id}.json
```

### Required runtime skill

```text
skills/requirement_atomization_v1.json
```

### Owns

- loading candidate requirements,
- creating bounded atomization work packets,
- invoking atomization through Skill Runtime,
- validating skill output,
- validating candidate IDs,
- validating source reference preservation,
- rewriting requirement IDs deterministically,
- writing final atomic requirement ledger.

### Bounded work packet rule

C08 must not pass an unbounded large candidate package to a skill.

It should process one candidate requirement or a small configured batch of candidate requirements per skill run.

If C08 uses `CandidateRequirementPackage` as the skill input contract, it must pass a bounded temporary package containing only the candidate or batch being processed.

### Production default rule

Production atomization must use Skill Runtime.

C08 must not silently fall back to regex splitting, sentence splitting, or heuristic atomization when no skill definition is supplied.

A deterministic atomization helper may exist only if it is explicitly named as a test/dev helper, such as:

```text
atomize_candidate_package_deterministic_for_tests
```

That helper must not be used by the orchestrator or by the default production path.

### Must not own

- requirement governance,
- deduplication final decisions,
- conflict resolution,
- obligation planning,
- test generation,
- direct LLM calls.

### Done when

Candidate requirements can become atomic requirements through Skill Runtime, source traceability is preserved, and production code cannot accidentally use heuristic-only atomization.

## C09 Requirement Governance

### Purpose

Own converting `AtomicRequirementLedger` into `GovernedRequirementLedger`.

### Production mode

Hybrid.

### Inputs

- `AtomicRequirementLedger`
- project approval policy
- optional reviewer skill definitions

### Outputs

- `GovernedRequirementLedger`
- conflict report data
- clarification report data
- optional `SkillRunRecord` artifacts for reviewer skills

### Artifact input

```text
artifacts/{project_id}/{run_id}/04_atomic_requirements/atomic_requirement_ledger.json
```

### Artifact output

```text
artifacts/{project_id}/{run_id}/05_governed_requirements/governed_requirement_ledger.json
```

### Optional reviewer skills

```text
skills/unsupported_requirement_reviewer_v1.json
skills/atomicity_reviewer_v1.json
skills/conflict_reviewer_v1.json
skills/semantic_duplicate_reviewer_v1.json
```

### Owns

- requirement status transitions,
- validation,
- source traceability checks,
- duplicate detection workflow,
- conflict marking,
- out-of-scope marking,
- approval requirement marking,
- rejection reasons,
- governed ledger writing.

### Must not own

- source parsing,
- requirement extraction,
- atomization,
- obligation planning,
- test generation,
- direct LLM calls.

### Important rule

Reviewer skills may suggest findings, but code owns final statuses.

### Done when

The system has a governed requirement ledger with clear statuses, traceability, and blocked/conflicting/approval-required requirements marked.

## C10 Test Obligation Planning

### Purpose

Own converting governed requirements into a `TestObligationLedger`.

### Production mode

Mostly code.

### Inputs

- `GovernedRequirementLedger`
- `ProjectConfig`
- `ProjectConfig.coverage_policy`

Executor capability policy is optional/future for C10 unless and until it is explicitly defined in `docs/DATA_CONTRACTS.md`. C10 v1 must not invent executor capability behavior. Executor-specific behavior belongs primarily to C11 test case generation, C12 test validation and coverage, and C14 executor export.

### Outputs

- `TestObligationLedger`

### Artifact input

```text
artifacts/{project_id}/{run_id}/05_governed_requirements/governed_requirement_ledger.json
```

### Artifact output

```text
artifacts/{project_id}/{run_id}/06_test_obligations/test_obligation_ledger.json
```

### Owns

- deterministic obligation rules,
- requirement-type to obligation-type mapping,
- obligation IDs,
- obligation source reference inheritance,
- blocked/skipped obligation statuses,
- coverage status initialization.

### Must not own

- test case writing,
- conversational wording,
- semantic assertion drafting,
- raw document interpretation,
- executor compatibility validation or export,
- direct LLM calls.

### Done when

Every eligible governed requirement has required obligations or a clear blocked/skipped reason.

## C11 Test Case Generation

### Purpose

Own converting test obligations into draft executable test cases through C06 Skill Runtime.

### Production mode

Skill-required.

### Inputs

- `TestObligationLedger`
- linked governed requirements
- project config
- executor contract
- relevant source references
- test data policy

### Outputs

- `DraftTestSuite`
- `SkillRunRecord`

### Artifact input

```text
artifacts/{project_id}/{run_id}/06_test_obligations/test_obligation_ledger.json
```

### Artifact output

```text
artifacts/{project_id}/{run_id}/07_draft_tests/draft_test_suite.json
```

### Required runtime skills

```text
skills/test_case_writer_v1.json
skills/oracle_generator_v1.json
```

### Owns

- bounded test generation work packets,
- invoking test generation skills through Skill Runtime,
- draft conversation turns,
- draft assertions,
- preserving requirement IDs,
- preserving obligation IDs,
- preserving source references,
- writing draft test suite.

### Must not own

- raw document interpretation,
- requirement extraction,
- atomization,
- obligation planning,
- final validation,
- export eligibility,
- direct LLM calls.

### Done when

Every generated draft test links to known requirement IDs and obligation IDs, and no draft test is generated from raw documents.

## C12 Test Validation and Coverage

### Purpose

Own validating draft tests and producing coverage reports.

### Production mode

Mostly code.

### Inputs

- `DraftTestSuite`
- `GovernedRequirementLedger`
- `TestObligationLedger`
- optional `SourcePackage` for source chunk coverage

Policy-based validation may consume `ProjectConfig` in a future version only if the C12 component spec and data contracts define that input.

### Outputs

- `ValidatedTestSuite`
- `CoverageReport`
- rejected test records or validation findings

### Artifact outputs

```text
artifacts/{project_id}/{run_id}/08_validated_tests/validated_test_suite.json
artifacts/{project_id}/{run_id}/08_validated_tests/coverage_report.json
```

### Optional reviewer skills

```text
skills/test_case_reviewer_v1.json
skills/gap_analyzer_v1.json
```

### Owns

- schema validation,
- orphan test rejection,
- unknown link rejection,
- duplicate test detection,
- source traceability validation,
- export eligibility validation,
- coverage counting,
- blocked obligation reporting,
- rejected test reporting.

### Must not own

- test drafting,
- final human approval,
- executor export,
- direct LLM calls.

### Important rule

Optional reviewer skills may add quality findings, but final validation and coverage counts are code-owned.

### Done when

The system can say which requirements, obligations, source chunks, and tests are covered, blocked, skipped, rejected, or export eligible.

## C13 Review Report

### Purpose

Own creating human-readable review artifacts.

### Production mode

Mostly code.

### Inputs

- `ValidatedTestSuite`
- `CoverageReport`
- `GovernedRequirementLedger`
- `TestObligationLedger`

C13 consumes artifacts that have already passed upstream validation. It reports traceability and coverage status from those artifacts, but C12 owns full test link validation and coverage calculation.

### Outputs

- Human-readable review report.
- `ReviewReportMetadata`

### Artifact output

```text
artifacts/{project_id}/{run_id}/09_review_report/review_report.md
artifacts/{project_id}/{run_id}/09_review_report/review_report_metadata.json
```

### Optional runtime skill

```text
skills/review_summary_writer_v1.json
```

### Owns

- PM-readable coverage summaries,
- gaps,
- conflicts,
- unclear chunks,
- inferred assumptions,
- rejected tests,
- approval-needed items.

C13 must not re-run C12 cross-artifact validation, recalculate coverage, or change validation state.

### Must not own

- source extraction,
- atomization,
- obligation planning,
- test generation,
- final export,
- direct LLM calls.

### Done when

A PM or QA reviewer can inspect what was generated, why it was generated, what is blocked, and what needs approval.

## C14 Executor Export

### Purpose

Own exporting approved, valid, traceable tests to the executor contract.

### Production mode

Code-only.

### Inputs

- approved `ValidatedTestSuite`
- `ProjectConfig`
- executor contract
- test data policy

### Outputs

- `ExecutorExportPackage`

### Artifact output

```text
artifacts/{project_id}/{run_id}/10_executor_export/executor_export_package.json
```

### Owns

- export schema,
- executor compatibility,
- approved-test filtering,
- final export eligibility checks,
- target bot URL packaging,
- test suite metadata.

### Must not own

- test generation,
- validation reasoning,
- human review decisions,
- runtime skills,
- direct LLM calls.

### Done when

Only approved, valid, traceable, executor-compatible tests are exported.

## C15 End-to-End Orchestrator

### Purpose

Own running the pipeline end to end by calling components in order.

### Production mode

Code-only orchestration.

### Inputs

- project config path,
- source docs,
- artifact root,
- run ID,
- component options.

### Outputs

- pipeline run state,
- stage artifacts,
- logs,
- final review/export artifacts when requested.

### Owns

- component ordering,
- state transitions,
- resumability,
- checkpoint detection,
- CLI entry points,
- pipeline logs,
- failure reporting.

### Must not own

- source parsing logic,
- requirement extraction reasoning,
- atomization reasoning,
- test writing,
- validation logic,
- direct LLM calls.

### Important rule

The orchestrator calls components. It does not perform LLM reasoning.

### Done when

The orchestrator can run the implemented components in sequence, stop on clear errors, and resume from existing valid artifacts where appropriate.

## Runtime Skill Inventory

The following runtime skills are expected as the product matures.

| Skill | Owning component | Required for v1 production? | Purpose |
|---|---|---:|---|
| `requirement_extraction_v1` | C07 | Yes | Extract candidate requirements from bounded source chunks. |
| `requirement_atomization_v1` | C08 | Yes | Split candidate requirements into atomic requirements. |
| `unsupported_requirement_reviewer_v1` | C09 | Later / optional | Identify unsupported or over-inferred requirements. |
| `atomicity_reviewer_v1` | C09 | Later / optional | Identify non-atomic requirements. |
| `conflict_reviewer_v1` | C09 | Later / optional | Identify conflicting requirements. |
| `semantic_duplicate_reviewer_v1` | C09 | Later / optional | Identify semantic duplicate requirements. |
| `test_case_writer_v1` | C11 | Yes when C11 is built | Draft test cases from obligations. |
| `oracle_generator_v1` | C11 | Yes when C11 is built | Draft expected outcomes and assertions. |
| `test_case_reviewer_v1` | C12 | Later / optional | Add quality findings for generated tests. |
| `gap_analyzer_v1` | C12/C13 | Later / optional | Identify missing scope or blocked coverage. |
| `review_summary_writer_v1` | C13 | Later / optional | Write readable summary text for review reports. |

## Artifact Stage Map

| Stage | Path |
|---|---|
| Project config | `00_project_config/project_config.json` |
| Documents | `01_documents/documents.json` |
| Source package | `02_source_package/source_package.json` |
| Candidate requirements | `03_candidate_requirements/candidate_requirement_package.json` |
| Atomic requirements | `04_atomic_requirements/atomic_requirement_ledger.json` |
| Governed requirements | `05_governed_requirements/governed_requirement_ledger.json` |
| Test obligations | `06_test_obligations/test_obligation_ledger.json` |
| Draft tests | `07_draft_tests/draft_test_suite.json` |
| Validated tests and coverage | `08_validated_tests/validated_test_suite.json`, `08_validated_tests/coverage_report.json` |
| Review | `09_review_report/review_report.md`, `09_review_report/review_report_metadata.json` |
| Executor export | `10_executor_export/executor_export_package.json` |
| Skill runs | `skill_runs/{skill_run_id}.json` |

All paths are relative to:

```text
artifacts/{project_id}/{run_id}/
```

## Component Drift Checklist

A component has drifted if it:

- calls an LLM directly,
- bypasses C06 Skill Runtime,
- generates tests from raw documents,
- skips required artifacts,
- emits downstream artifacts outside its component boundary,
- lacks tests,
- lacks traceability validation,
- silently accepts unknown IDs,
- silently accepts source-less validated requirements,
- silently falls back to heuristics in a skill-required production component,
- lets the orchestrator reason instead of orchestrate.

If drift happens, fix the component before continuing to the next one.
