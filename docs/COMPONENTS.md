# Components

The v1 system is implemented one component at a time in this order.

| ID | Component | Primary Responsibility |
| --- | --- | --- |
| C00 | Bootstrap and architecture docs | Repository documentation and scaffolding only. |
| C01 | Shared schemas | Canonical schema definitions and validation. |
| C02 | Artifact store | Local JSON artifact read/write, versioned paths, checksums, and existence validation. |
| C03 | Project configuration | Loading, validating, and saving `ProjectConfig`. |
| C04 | Document ingestion | Reading source documents and creating `Document` records. |
| C05 | Source ledger | Chunking documents into `SourceChunk` records and `SourcePackage`. |
| C06 | Skill runtime | Loading skills, executing runtime skills, validating skill I/O, and recording `SkillRunRecord`. |
| C07 | Requirement extraction | Converting `SourcePackage` into `CandidateRequirementPackage` through the Skill Runtime. |
| C08 | Requirement atomization | Converting candidates into `AtomicRequirementLedger` while preserving source references. |
| C09 | Requirement governance | Status decisions, deduplication policy, conflicts, approval gates, and governed ledger creation. |
| C10 | Test obligation planning | Converting governed requirements into `TestObligationLedger`. |
| C11 | Test case generation | Generating `DraftTestSuite` from obligations through the Skill Runtime. |
| C12 | Test validation and coverage | Creating `ValidatedTestSuite` and `CoverageReport`; rejecting orphan or ineligible tests. |
| C13 | Review report | Creating a human-readable review report without changing validation state. |
| C14 | Executor export | Creating export packages from eligible validated tests. |
| C15 | End-to-end orchestrator | CLI orchestration across completed components without bypassing contracts. |

Each component has a detailed spec in `docs/components/`.

