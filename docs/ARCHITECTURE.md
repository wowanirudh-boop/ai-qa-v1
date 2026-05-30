# Architecture

## Product Purpose

The AI Test Generation System is a requirements-to-test compiler for chatbot testing. It turns source documents into validated, traceable test suites that can be reviewed by humans and exported to an executor.

The system exists to preserve traceability and reviewability. A generated test is not acceptable unless it can be traced back through the pipeline to the requirement and source evidence that justify it, or to an explicitly approved non-source origin such as an assumption or system default.

## Full Pipeline

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

The artifact flow for v1 is:

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

## Modular Monolith

v1 is a modular monolith with a CLI and local JSON artifacts. Components live in one Python package, but each component has a clear contract, its own tests, and a narrow responsibility.

This keeps early development simple while preserving boundaries that can later support service extraction if the product requires it. Component APIs should pass validated data contracts or artifact paths, not loose dictionaries with undocumented shape.

## Why Tests Cannot Come Directly From Raw Docs

Raw documents are ambiguous, duplicated, incomplete, and often contain context that is not testable. Generating tests directly from raw documents would make it hard to prove what each test covers, hard to reject unsupported output, and hard to maintain deterministic validation.

The required pipeline separates reasoning from control:

- `SourceChunk` records preserve evidence.
- `CandidateRequirement` records capture possible requirements from that evidence.
- `AtomicRequirement` records normalize each requirement into one testable statement.
- `GovernedRequirementLedger` records status, deduplication, conflicts, and approvals.
- `TestObligation` records define what must be tested before any full test case is drafted.

Only after these steps may the system generate draft test cases.

## Code vs Runtime Skills

Deterministic code owns:

- orchestration
- schemas and validation
- artifact persistence
- IDs and state
- deduplication workflow
- coverage calculations
- export eligibility
- CLI behavior

Runtime skills own LLM reasoning only. A runtime skill may help interpret text, compare semantic similarity, atomize language, or draft test content. A runtime skill must be invoked only through the Skill Runtime component.

No component may call an LLM directly except through the Skill Runtime.

## Role of Artifacts

Artifacts are local JSON records produced and consumed by components. They make the pipeline inspectable, repeatable, and testable.

Each component reads known input artifact paths and writes known output artifact paths. The Artifact Store is responsible for local JSON read/write behavior, checksums, existence checks, and versioned paths. Business components must not reinvent persistence.

Conservative v1 artifact root:

```text
artifacts/{project_id}/{run_id}/
```

Each component spec defines its expected input and output paths under that root.

## Role of Traceability

Traceability is a product requirement, not a reporting convenience. The system must maintain this chain:

```text
SourceChunk -> Requirement -> Obligation -> TestCase
```

Validated source-derived requirements need `source_refs`. Exportable test cases need known `requirement_ids`, known `obligation_ids`, and source references inherited from their linked requirements and obligations.

The validator must reject orphan test cases, unknown links, and tests that are not export eligible.

