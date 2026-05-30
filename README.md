# AI Test Generation System

This repository is the architecture bootstrap for an AI Test Generation System for chatbot testing.

The product is a requirements-to-test compiler. It converts source requirements documents into traceable, validated chatbot test suites and executor export packages.

This bootstrap does not implement the system. It creates the permanent repository documentation, data contracts, TDD rules, component specs, and minimal source tree needed for future component-by-component implementation.

## Pipeline

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

Hard rule: test cases must never be generated directly from raw documents. Test generation must use governed `AtomicRequirement` records and planned `TestObligation` records.

## Repository Map

- `AGENTS.md`: operational rules for future Codex chats.
- `docs/ARCHITECTURE.md`: product and system architecture.
- `docs/DATA_CONTRACTS.md`: canonical v1 data contracts and validation rules.
- `docs/TDD_RULES.md`: required test-first process.
- `docs/COMPONENTS.md`: component list and boundaries.
- `docs/PIPELINE.md`: artifact flow and traceability.
- `docs/CODEX_WORKFLOW.md`: how future Codex chats should implement components.
- `docs/components/`: component specs C00 through C15.
- `src/ai_testgen/`: future Python package root.
- `tests/`: future unit and fixture tests.
- `examples/demo_project/docs/`: future example source documents.
- `skills/`: future runtime skill definitions.

## Current State

This repo is intentionally documentation-first. Future chats should implement one component at a time by reading `AGENTS.md`, `docs/TDD_RULES.md`, and the relevant file under `docs/components/`.

