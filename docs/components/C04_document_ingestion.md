# C04 Document Ingestion

## Purpose

Own reading source documents and creating `Document` records.

## Inputs

- Validated `ProjectConfig`.
- Source files from configured `source_paths`.

Input artifact path conventions:

- Reads `artifacts/{project_id}/{run_id}/00_project_config/project_config.json`.
- Reads source documents from paths listed in `ProjectConfig.source_paths`.

## Outputs

- Document collection artifact.

Output artifact path conventions:

- `artifacts/{project_id}/{run_id}/01_documents/documents.json`

## Data contracts used

- `ProjectConfig`
- `Document`

## Files/modules to create

May create:

- `src/ai_testgen/document_ingestion.py`
- `tests/unit/test_document_ingestion.py`
- `tests/unit/fixtures/golden/document_ingestion/`

## CLI command

`ai-testgen ingest-documents --config artifacts/{project_id}/{run_id}/00_project_config/project_config.json`

## Runtime skills used

None.

## Deterministic code responsibilities

- Discover configured source documents.
- Read supported local text formats for v1.
- Create deterministic `Document` IDs and content checksums.
- Mark skipped or failed documents without extracting requirements.

## Validation rules

- Each `Document` must include `document_id`, `project_id`, `source_path`, `title`, `content_checksum`, and `ingestion_status`.
- Duplicate source paths should not create duplicate successful documents.
- Missing source paths should fail clearly.

## Required tests

- Happy path document ingestion.
- Missing source path failure.
- Duplicate document handling.
- Checksum stability.
- Golden fixture for documents output.

## Golden fixtures

Useful. Include a small source document and expected `documents.json`.

## Non-goals

Must not implement:

- source chunking
- requirement extraction
- semantic classification
- test generation
- runtime skill calls

## Definition of done

- Source files become valid `Document` records.
- Tests prove checksums, required fields, and error handling.
- No `SourceChunk` or requirement artifacts are produced.

