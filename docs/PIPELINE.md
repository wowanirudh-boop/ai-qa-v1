# Pipeline

The v1 pipeline is artifact-driven. Each stage consumes validated JSON artifacts and writes a new JSON artifact for the next stage.

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

## Artifact Path Convention

Conservative v1 artifact root:

```text
artifacts/{project_id}/{run_id}/
```

Recommended stage paths:

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
10_executor_export/executor_export_package.json
```

## Traceability Chain

The required traceability chain is:

```text
SourceChunk -> Requirement -> Obligation -> TestCase
```

Traceability is represented by IDs and `source_refs`:

- `SourceChunk.chunk_id` identifies source evidence.
- `CandidateRequirement.source_refs` points to source chunks.
- `AtomicRequirement.source_refs` preserves source evidence unless the requirement has an approved non-source origin.
- `TestObligation.requirement_id` links to a governed requirement and inherits its source references.
- `TestCase.requirement_ids` and `TestCase.obligation_ids` link every test to requirements and obligations.

## Validation Gates

- Requirement extraction cannot produce final requirements.
- Requirement atomization cannot generate tests.
- Governance must mark duplicates, conflicts, rejected items, and approval gates before obligations exist.
- Obligation planning cannot create obligations from rejected requirements.
- Test generation cannot read raw documents as a direct source.
- Validation must reject orphan test cases.
- Export must include only eligible tests.

