# C05 Source Ledger

## Purpose

Own chunking documents into `SourceChunk` records and creating a `SourcePackage`.

## Inputs

- Document collection artifact.
- Source document content referenced by each `Document`.

Input artifact path conventions:

- `artifacts/{project_id}/{run_id}/01_documents/documents.json`

## Outputs

- `SourcePackage` containing `SourceChunk` records.

Output artifact path conventions:

- `artifacts/{project_id}/{run_id}/02_source_package/source_package.json`

## Data contracts used

- `Document`
- `SourceRef`
- `SourceChunk`
- `SourcePackage`

## Files/modules to create

May create:

- `src/ai_testgen/source_ledger.py`
- `tests/unit/test_source_ledger.py`
- `tests/unit/fixtures/golden/source_ledger/`

## CLI command

`ai-testgen build-source-package --documents artifacts/{project_id}/{run_id}/01_documents/documents.json`

## Runtime skills used

None.

## Deterministic code responsibilities

- Split document text into deterministic chunks.
- Assign stable chunk IDs.
- Compute chunk checksums.
- Set initial `processing_status`.
- Create a source package checksum.

## Validation rules

- Each `SourceChunk` must include `chunk_id`, `document_id`, `text`, `checksum`, and `processing_status`.
- `processing_status` must use the documented enum.
- Every chunk must reference a known document.
- Empty documents should not produce empty text chunks.

## Required tests

- Chunking happy path.
- Empty document behavior.
- Chunk ID stability.
- Checksum stability.
- Source package validation.
- Golden fixture for source package output.

## Golden fixtures

Useful. Include input documents and expected source package.

## Non-goals

Must not implement:

- requirement extraction
- non-testable context classification using LLM reasoning
- candidate requirements
- test generation
- runtime skill calls

## Definition of done

- Documents become deterministic source chunks.
- Source package validates against the contract.
- Tests prove traceability from chunk to document.

