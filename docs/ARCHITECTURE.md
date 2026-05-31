# Architecture

## Product Purpose

The AI Test Generation System is a requirements-to-test compiler for chatbot testing.

It turns source documents such as bot flow diagrams, FAQ/KB documents, context documents, API references, policies, sample conversations, and release notes into validated, traceable test suites that can be reviewed by humans and exported to a test executor.

The system exists to preserve traceability, reviewability, and controlled generation.

A generated test is not acceptable unless it can be traced back through the pipeline to the requirement and source evidence that justify it, or to an explicitly approved non-source origin such as a human-approved assumption, user-added requirement, or system default.

The product should not behave like a one-shot test generator. It should behave like a compiler:

```text
source evidence
  -> candidate requirements
  -> atomic requirements
  -> governed requirements
  -> test obligations
  -> executable test cases
```

## Core System Definition

The system is an AI-assisted requirements-to-test compiler.

Its purpose is to:

1. ingest source documents,
2. preserve source evidence as stable chunks,
3. extract source-backed candidate requirements,
4. split those candidates into atomic testable requirements,
5. govern, deduplicate, validate, and approve requirements,
6. expand validated requirements into test obligations,
7. generate draft executable test cases from obligations,
8. validate test cases before export,
9. produce human-reviewable coverage and gap reports,
10. export only approved, traceable tests to the executor.

The system must not generate production test cases directly from raw documents.

## Full Pipeline

The conceptual pipeline is:

```text
Source Document
-> Source Chunk
-> Candidate Requirement
-> Atomic Requirement
-> Governed Requirement
-> Test Obligation
-> Draft Test Case
-> Validated Test Suite
-> Review Report
-> Executor Export Package
```

The v1 artifact flow is:

```text
ProjectConfig
-> Documents
-> SourcePackage
-> CandidateRequirementPackage
-> AtomicRequirementLedger
-> GovernedRequirementLedger
-> TestObligationLedger
-> DraftTestSuite
-> ValidatedTestSuite
-> CoverageReport
-> ReviewReport
-> ExecutorExportPackage
```

The traceability chain is:

```text
SourceChunk
  -> CandidateRequirement
  -> AtomicRequirement
  -> GovernedRequirement
  -> TestObligation
  -> TestCase
```

## Non-Negotiable Architecture Rules

These rules apply to every component:

1. Do not generate test cases directly from raw documents.
2. All production test generation must flow through `AtomicRequirement` and `TestObligation`.
3. Code owns orchestration, schemas, validation, persistence, IDs, state, deterministic status transitions, deduplication workflow, coverage calculations, and export eligibility.
4. Runtime skills own LLM reasoning only.
5. No subsystem may call an LLM directly except through C06 Skill Runtime.
6. Skill-required components must fail clearly if the required skill definition is missing or invalid.
7. Skill-required production components must not silently fall back to heuristic or regex-only behavior.
8. Every validated source-derived `AtomicRequirement` must have `source_refs`.
9. Requirements without source evidence must be explicitly marked as `inferred`, `assumption`, `user_added`, or `system_default`, and must require approval before export.
10. Every `TestCase` must have non-empty `requirement_ids` and `obligation_ids`.
11. Exportable test cases must have source references inherited from linked requirements and obligations, unless they are explicitly approved non-source tests.
12. Reject orphan test cases.
13. Reject test cases with unknown requirement IDs.
14. Reject test cases with unknown obligation IDs.
15. Conflicting requirements cannot generate normal exportable obligations.
16. Rejected requirements cannot generate obligations.
17. Every component must be independently testable.
18. Every component must have unit tests and, where useful, golden fixtures.
19. Build v1 as a modular monolith with CLI and local JSON artifacts.
20. Do not implement future components from inside a current component.

## Modular Monolith

v1 is a modular monolith with a CLI and local JSON artifacts.

Components live in one Python package, but each component has:

- a clear contract,
- its own tests,
- a narrow responsibility,
- explicit input artifacts,
- explicit output artifacts,
- clear non-goals.

This keeps early development simple while preserving boundaries that can later support service extraction if the product requires it.

Component APIs should pass validated data contracts or artifact paths, not loose dictionaries with undocumented shape.

## Why Tests Cannot Come Directly From Raw Docs

Raw documents are ambiguous, duplicated, incomplete, and often contain context that is not testable.

Generating tests directly from raw documents would make it hard to prove:

- what each test covers,
- which source supports each test,
- whether the test was made up,
- whether a requirement was missed,
- whether a test obligation was missed,
- whether a test is export eligible.

The required pipeline separates reasoning from control:

- `SourceChunk` records preserve evidence.
- `CandidateRequirement` records capture possible requirements from that evidence.
- `AtomicRequirement` records normalize each requirement into one testable statement.
- `GovernedRequirementLedger` records status, deduplication, conflicts, approvals, and rejected requirements.
- `TestObligation` records define what must be tested before any full test case is drafted.
- `TestCase` records must link back to obligations and requirements.

Only after these steps may the system generate draft test cases.

## Atomic Requirements

Atomic requirements are the central unit of the system.

An atomic requirement must describe:

- one behavior,
- one trigger or condition set,
- one expected outcome,
- one source-backed or explicitly approved non-source claim,
- one testable requirement.

A broad requirement such as:

```text
The bot should help users return products and explain refund timelines.
```

must be decomposed into atomic requirements such as:

```text
The bot should recognize when the user wants to return a product.
The bot should ask for an order ID if the user has not provided one.
The bot should explain the documented refund timeline when refund timing is requested.
```

Production atomization is a semantic reasoning task and must be performed through a runtime skill.

Deterministic code may validate atomicity, rewrite IDs, check traceability, and persist artifacts. It must not rely on regex or string splitting as the production atomization method.

Heuristic atomization helpers may exist only for explicitly named test/dev helpers. They must not be used by the orchestrator or by the default production path.

## Test Obligations

A test obligation is a required testing duty derived from a governed requirement.

An atomic requirement does not directly become a test case. It first becomes one or more obligations.

Example:

```text
Requirement:
The bot should ask for order ID before checking return eligibility.

Obligations:
- Test missing order ID.
- Test provided order ID.
- Test that the bot does not check eligibility before order ID is collected.
```

Test obligation planning should be mostly deterministic.

For v1, C10 uses requirement type, `ProjectConfig.coverage_policy`, and requirement status to decide which obligations are required.

Executor capability policy is optional/future for C10 unless and until it is explicitly defined in `docs/DATA_CONTRACTS.md`. C10 must not invent executor capability behavior. Executor-specific behavior is handled later by C11 when drafting executor-compatible tests, C12 when validating executor compatibility, and C14 when exporting to the executor contract.

Runtime skills may assist later in writing natural test conversations, but they should not be the sole mechanism that decides which obligations exist.

## Code vs Runtime Skills

The system separates deterministic control from LLM reasoning.

### Deterministic code owns

- pipeline orchestration,
- component boundaries,
- schema validation,
- artifact persistence,
- artifact paths,
- checksums,
- IDs,
- status transitions,
- source coverage accounting,
- requirement traceability checks,
- obligation coverage calculations,
- duplicate detection workflow,
- export eligibility,
- CLI behavior,
- retries,
- error handling,
- logging,
- test execution handoff.

### Runtime skills own

Runtime skills own LLM reasoning tasks such as:

- interpreting source text,
- extracting candidate requirements,
- identifying non-testable context,
- identifying unclear or out-of-scope chunks,
- splitting broad requirements into atomic requirements,
- interpreting conditions and exceptions,
- comparing semantic similarity,
- reviewing unsupported claims,
- reviewing conflicts,
- drafting test case conversations,
- drafting semantic assertions,
- identifying gaps for human review.

### Runtime skills must not own

Runtime skills must not own:

- pipeline control,
- artifact persistence,
- final IDs,
- final status transitions,
- export eligibility,
- schema enforcement,
- final coverage counts,
- final approval decisions,
- direct writes to business artifacts outside their declared output path.

## Skill Runtime Rule

All runtime skill execution must go through C06 Skill Runtime.

No business component may call an LLM provider directly.

Correct pattern:

```text
business component
  -> C06 Skill Runtime
    -> skill definition
      -> controlled adapter
        -> validated skill output
```

Incorrect pattern:

```text
business component
  -> direct LLM API call
```

C06 may use fake/local skills in unit tests. That is expected.

Provider-specific LLM adapters may be added later inside the Skill Runtime boundary. Business components should not change when the provider adapter changes.

## Skill-Required Components

Some components are skill-required in production.

A skill-required component must:

1. load a declared `SkillDefinition`,
2. validate the skill definition,
3. invoke the skill through C06 Skill Runtime,
4. validate the skill output against the expected contract,
5. validate cross-artifact traceability,
6. write deterministic final artifacts through the Artifact Store,
7. record a `SkillRunRecord`,
8. fail clearly if the skill definition is missing, invalid, or fails execution.

A skill-required component must not silently fall back to deterministic heuristics in production.

Unit tests may use fake skill runtimes. That does not make the component code-only.

## Component Execution Modes

Each component has a production execution mode:

| Component | Production mode | Meaning |
|---|---|---|
| C00 Bootstrap and architecture docs | Code-only / docs-only | Creates docs and scaffolding only. |
| C01 Shared schemas | Code-only | Defines and validates contracts. |
| C02 Artifact store | Code-only | Reads/writes local JSON artifacts. |
| C03 Project configuration | Code-only | Loads, validates, and saves project config. |
| C04 Document ingestion | Code-only | Reads source files and creates document records. |
| C05 Source ledger | Code-only | Chunks documents into stable source chunks. |
| C06 Skill runtime | Skill infrastructure | Loads and executes skills; tests may use fake skills. |
| C07 Requirement extraction | Skill-required | Extracts candidate requirements through Skill Runtime. |
| C08 Requirement atomization | Skill-required | Atomizes candidate requirements through Skill Runtime. |
| C09 Requirement governance | Hybrid | Code owns statuses; reviewer skills may assist. |
| C10 Test obligation planning | Mostly code | Deterministic obligation rules; optional helper skills later. |
| C11 Test case generation | Skill-required | Drafts test cases and assertions through Skill Runtime. |
| C12 Test validation and coverage | Mostly code | Code validates; optional reviewer skills may add findings. |
| C13 Review report | Mostly code | Produces review artifacts; optional summarization skill later. |
| C14 Executor export | Code-only | Exports only approved, valid, traceable tests. |
| C15 End-to-end orchestrator | Code-only orchestration | Runs components; does not perform LLM reasoning itself. |

## Runtime Skill Definitions and Prompts

Runtime prompts are product runtime assets. They are different from Codex build prompts.

Runtime skill definitions live under `skills/`.

For v1, a skill definition may be represented as a JSON file such as:

```text
skills/requirement_extraction_v1.json
skills/requirement_atomization_v1.json
skills/test_case_writer_v1.json
```

If the Skill Runtime later supports directory-based skills, the directory may contain:

```text
skills/requirement_extraction_v1/
  skill.yaml
  prompt.md
  input_example.json
  output_example.json
  golden/
```

Either representation is acceptable only if C06 Skill Runtime can load and validate it.

Each runtime skill definition must specify:

- skill ID,
- version,
- purpose,
- input contract,
- output contract,
- prompt template or prompt path,
- JSON-only output requirement,
- grounding rules,
- source reference rules,
- uncertainty rules,
- allowed adapter type,
- test fixture behavior.

Runtime prompts must tell the model:

- use only the provided input artifact,
- do not infer unsupported facts,
- preserve source references,
- return only the declared JSON output contract,
- do not control workflow,
- do not generate downstream artifact types unless that is the skill’s declared output.

## Bounded LLM Work Packets

LLMs should not be asked to reason over unbounded project context.

Skill-required components must pass bounded work packets to skills.

Examples of bounded work packets:

```text
one SourceChunk
a small configured batch of SourceChunks
one CandidateRequirement
a small configured batch of CandidateRequirements
one TestObligation
a small configured batch of TestObligations
```

If a component uses a larger artifact type such as `SourcePackage` or `CandidateRequirementPackage` as the skill input contract, the component must still ensure that the artifact passed to the skill is bounded by configuration.

A component must not pass an entire large project corpus to a skill by default.

## Role of Artifacts

Artifacts are local JSON records produced and consumed by components.

They make the pipeline:

- inspectable,
- repeatable,
- testable,
- reviewable,
- resumable.

Each component reads known input artifact paths and writes known output artifact paths.

The Artifact Store is responsible for:

- local JSON read/write behavior,
- stable formatting,
- checksums,
- existence checks,
- versioned paths,
- path safety.

Business components must not reinvent persistence.

Conservative v1 artifact root:

```text
artifacts/{project_id}/{run_id}/
```

Each component spec defines its expected input and output paths under that root.

## Role of Traceability

Traceability is a product requirement, not a reporting convenience.

The system must maintain this chain:

```text
SourceChunk -> Requirement -> Obligation -> TestCase
```

Validated source-derived requirements need `source_refs`.

Exportable test cases need:

- known `requirement_ids`,
- known `obligation_ids`,
- source references inherited from linked requirements and obligations,
- approval if the source is non-documentary, such as `inferred`, `assumption`, `user_added`, or `system_default`.

The validator must reject:

- orphan test cases,
- unknown requirement links,
- unknown obligation links,
- export attempts for rejected tests,
- export attempts for unresolved conflicting requirements,
- export attempts for unapproved inferred requirements.

## Source Coverage Ledger

Every source chunk must be accounted for.

A `SourceChunk` starts as:

```text
not_processed
```

After extraction and source coverage accounting, each eligible chunk should eventually be assigned one of:

```text
requirements_extracted
non_testable_context
duplicate
out_of_scope
unclear
failed_processing
```

No source chunk should disappear silently.

For v1, if the current `CandidateRequirementPackage` contract cannot represent per-chunk extraction outcomes, the data contracts and schemas should be extended to include a controlled chunk-level extraction result structure.

That structure should allow C07 to record:

- chunk ID,
- resulting processing status,
- candidate requirement IDs produced from the chunk,
- optional rationale,
- optional error message.

## Requirement Governance

Requirement governance owns the trusted requirement ledger.

It must handle:

- validation,
- deduplication,
- conflict detection,
- source traceability checks,
- status transitions,
- out-of-scope filtering,
- approval requirements,
- rejection reasons.

Requirement governance is hybrid:

- code owns final statuses and eligibility,
- reviewer skills may suggest atomicity issues, unsupported claims, semantic duplicates, and conflicts.

Reviewer skill findings are not final state. Code must validate and apply final state transitions.

## Test Obligation Planning

Test obligation planning turns governed requirements into required test duties.

This component should be mostly deterministic.

It should use rules such as:

```text
entity_collection requirement
  -> missing entity obligation
  -> provided entity obligation
  -> invalid entity obligation when validation rules exist

business_rule requirement
  -> positive case obligation
  -> negative case obligation
  -> boundary case obligation when a threshold exists

faq_answer requirement
  -> direct question obligation
  -> paraphrase obligation
  -> adjacent-topic negative obligation

api_behavior requirement
  -> success response obligation
  -> documented error response obligation
  -> timeout/unavailable obligation only if documented or approved
```

The LLM may help later with wording or gap analysis, but obligation existence should not depend only on an LLM remembering to create it.

## Test Case Generation

Test case generation is skill-required in production.

The test generator must not read raw source documents directly.

It should receive only:

- one or more test obligations,
- linked governed requirements,
- relevant source references,
- allowed test data policy,
- executor contract,
- project configuration.

The test generation skill may draft:

- conversation turns,
- expected bot behavior,
- semantic assertions,
- must-include meanings,
- must-not-include meanings,
- preconditions,
- test data needs.

Code must validate:

- schema correctness,
- requirement links,
- obligation links,
- source references,
- executor compatibility,
- export eligibility.

## Validation and Coverage

Validation and coverage are mostly code-owned.

The validation layer must check:

- all schemas,
- all IDs,
- all links,
- source traceability,
- orphan tests,
- duplicate tests,
- export eligibility,
- unresolved conflicts,
- unapproved inferred scope,
- missing required obligations,
- requirement coverage,
- source chunk coverage.

Optional reviewer skills may add quality findings, but final validation is deterministic code.

## Human Review

The system should expose uncertainty instead of hiding it.

Human review should show:

- validated requirements,
- inferred requirements,
- assumptions,
- conflicts,
- unclear chunks,
- out-of-scope chunks,
- generated obligations,
- generated tests,
- rejected tests,
- coverage gaps,
- source evidence.

Human actions may include:

- approve,
- reject,
- edit,
- mark out of scope,
- resolve conflict,
- approve inferred requirement,
- request regeneration,
- add manual requirement.

## Export Eligibility

The Executor Export component must export only test cases that are:

- schema valid,
- approved or otherwise export eligible,
- linked to known obligations,
- linked to known requirements,
- traceable to source evidence or approved non-source origin,
- not blocked by unresolved conflicts,
- compatible with the executor contract.

Export must be code-only.

No LLM should decide final export eligibility.

## Drift Prevention Rules

The following are signs of implementation drift:

- A component directly calls an LLM provider.
- A skill-required component works in production without a skill definition.
- A skill-required component silently falls back to regex or heuristic output.
- Test cases are generated from raw docs.
- Test cases lack requirement IDs.
- Test cases lack obligation IDs.
- Requirements lack source references without being marked as approved non-source.
- Source chunks remain unaccounted for after extraction.
- Prompts are embedded randomly inside business components instead of loaded through Skill Runtime.
- The orchestrator performs reasoning instead of calling components.

If drift occurs, fix the relevant component docs, tests, and implementation before continuing to later components.

## V1 Non-Goals

v1 should not attempt to solve everything.

Non-goals for v1:

- microservice deployment,
- complex UI,
- real browser test execution,
- complex OCR-heavy diagram understanding,
- provider-specific LLM implementation in every component,
- one-shot test generation from large contexts,
- perfect automatic conflict resolution,
- fully autonomous approval.

The v1 goal is a reliable, inspectable, artifact-driven pipeline that proves the architecture and produces traceable test suites.
