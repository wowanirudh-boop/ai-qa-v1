# C01 Shared Schemas

## Purpose

Own canonical schema definitions and validation for every v1 data contract.

## Inputs

- `docs/DATA_CONTRACTS.md`
- JSON-like Python objects or dictionaries to validate.

Input artifact path conventions:

- Schema validators should accept in-memory data.
- File loading belongs to C02 Artifact Store.

## Outputs

- Validated contract objects or validation errors.

Output artifact path conventions:

- None. This component does not write artifacts directly.

## Data contracts used

- All contracts in `docs/DATA_CONTRACTS.md`.

## Files/modules to create

May create:

- `src/ai_testgen/schemas.py`
- `src/ai_testgen/validators.py`
- `tests/unit/test_schemas.py`
- `tests/unit/fixtures/golden/schemas/`

## CLI command

None for v1 unless a future request explicitly asks for schema validation from the CLI.

## Runtime skills used

None.

## Deterministic code responsibilities

- Define canonical contract shapes.
- Validate required fields, optional fields, enums, ID references where local context is supplied, and numeric ranges.
- Return useful validation errors without performing pipeline orchestration.

## Validation rules

- Enforce all rules in `docs/DATA_CONTRACTS.md`.
- Reject unknown fields unless the contract explicitly allows `metadata`.
- Enforce status enums exactly.
- Enforce non-empty `source_refs`, `requirement_ids`, and `obligation_ids` where required.

## Required tests

- Schema contract tests for every contract.
- Invalid input tests for missing required fields.
- Invalid enum tests.
- Confidence range tests.
- Traceability field tests for requirements, obligations, and test cases.

## Golden fixtures

Useful. Include small valid and invalid JSON fixtures for representative contracts:

- `ProjectConfig`
- `SourceChunk`
- `AtomicRequirement`
- `TestObligation`
- `TestCase`
- `CoverageReport`

## Non-goals

Must not implement:

- artifact persistence
- pipeline orchestration
- CLI commands
- runtime skills
- requirement extraction
- test generation

## Definition of done

- All v1 contracts have deterministic validators.
- Unit tests cover required fields, enums, and key traceability rules.
- No component business logic exists outside schema validation.

