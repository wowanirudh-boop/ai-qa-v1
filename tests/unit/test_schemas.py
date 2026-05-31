import copy
import json
from pathlib import Path

import pytest

from ai_testgen.schemas import (
    Assertion,
    AtomicRequirement,
    AtomicRequirementLedger,
    CandidateRequirement,
    CandidateRequirementPackage,
    ChunkExtractionResult,
    ConversationTurn,
    CoverageReport,
    Document,
    DraftTestSuite,
    ExecutorExportPackage,
    GovernedRequirementLedger,
    PipelineRunState,
    ProjectConfig,
    ReviewReportMetadata,
    SchemaValidationError,
    SkillDefinition,
    SkillRunRecord,
    SourceChunk,
    SourcePackage,
    SourceRef,
    TestCase as SchemaTestCase,
    TestObligation as SchemaTestObligation,
    TestObligationLedger as SchemaTestObligationLedger,
    ValidatedTestSuite,
)
from ai_testgen.validators import (
    validate_executor_export_package,
    validate_obligation_links,
    validate_test_case_links,
)


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "schemas"


def source_ref() -> dict:
    return {"document_id": "doc_001", "chunk_id": "chunk_001"}


def source_chunk() -> dict:
    return {
        "chunk_id": "chunk_001",
        "document_id": "doc_001",
        "text": "The bot must ask for an order number.",
        "checksum": "sha256:def456",
        "processing_status": "not_processed",
    }


def candidate_requirement() -> dict:
    return {
        "candidate_id": "cand_001",
        "statement": "The bot must ask for an order number.",
        "requirement_type_guess": "functional",
        "source_refs": [source_ref()],
        "confidence": 0.91,
    }


def atomic_requirement(**overrides: object) -> dict:
    data = {
        "requirement_id": "req_001",
        "statement": "The bot asks for an order number.",
        "requirement_type": "functional",
        "status": "validated",
        "origin": "source_derived",
        "source_refs": [source_ref()],
        "candidate_ids": ["cand_001"],
    }
    data.update(overrides)
    return data


def obligation_data(**overrides: object) -> dict:
    data = {
        "obligation_id": "obl_001",
        "requirement_id": "req_001",
        "obligation_type": "positive",
        "status": "planned",
        "source_refs": [source_ref()],
    }
    data.update(overrides)
    return data


def conversation_turn() -> dict:
    return {"turn_id": "turn_001", "speaker": "user", "text": "Where is my order?"}


def assertion() -> dict:
    return {
        "assertion_id": "assert_001",
        "assertion_type": "bot_response_contains_request",
        "target": "bot.final_response",
        "expected": "The bot asks for the order number.",
    }


def case_data(**overrides: object) -> dict:
    data = {
        "test_case_id": "tc_001",
        "title": "Order status requires order number",
        "status": "draft",
        "requirement_ids": ["req_001"],
        "obligation_ids": ["obl_001"],
        "turns": [conversation_turn()],
        "assertions": [assertion()],
    }
    data.update(overrides)
    return data


def coverage_report() -> dict:
    return {
        "coverage_report_id": "coverage_001",
        "project_id": "demo_chatbot",
        "validated_suite_id": "validated_suite_001",
        "requirement_counts": {"total": 1, "covered": 1, "uncovered": 0},
        "obligation_counts": {"total": 1, "covered": 1, "blocked": 0},
        "test_counts": {"total": 1, "export_eligible": 1, "rejected": 0},
        "source_chunk_counts": {"total": 1, "with_requirements": 1, "without_requirements": 0},
    }


CONTRACT_CASES = [
    (
        ProjectConfig,
        {
            "project_id": "demo_chatbot",
            "bot_name": "Demo Support Bot",
            "target_url": "https://example.test/chat",
            "coverage_policy": {"require_positive_tests": True},
            "approval_policy": {"allow_export_without_review": False},
        },
    ),
    (
        Document,
        {
            "document_id": "doc_001",
            "project_id": "demo_chatbot",
            "source_path": "docs/requirements.md",
            "title": "Requirements",
            "content_checksum": "sha256:abc123",
            "ingestion_status": "loaded",
        },
    ),
    (SourceRef, source_ref()),
    (SourceChunk, source_chunk()),
    (
        SourcePackage,
        {
            "source_package_id": "source_pkg_001",
            "project_id": "demo_chatbot",
            "document_ids": ["doc_001"],
            "chunks": [source_chunk()],
            "checksum": "sha256:pkg001",
        },
    ),
    (CandidateRequirement, candidate_requirement()),
    (
        ChunkExtractionResult,
        {
            "chunk_id": "chunk_001",
            "processing_status": "requirements_extracted",
            "candidate_ids": ["cand_001"],
            "rationale": "The chunk contains a testable bot behavior.",
        },
    ),
    (
        CandidateRequirementPackage,
        {
            "candidate_package_id": "cand_pkg_001",
            "project_id": "demo_chatbot",
            "source_package_id": "source_pkg_001",
            "candidates": [candidate_requirement()],
            "chunk_extraction_results": [
                {
                    "chunk_id": "chunk_001",
                    "processing_status": "requirements_extracted",
                    "candidate_ids": ["cand_001"],
                }
            ],
        },
    ),
    (AtomicRequirement, atomic_requirement()),
    (
        AtomicRequirementLedger,
        {
            "atomic_ledger_id": "atomic_ledger_001",
            "project_id": "demo_chatbot",
            "candidate_package_id": "cand_pkg_001",
            "requirements": [atomic_requirement()],
        },
    ),
    (
        GovernedRequirementLedger,
        {
            "governed_ledger_id": "gov_ledger_001",
            "project_id": "demo_chatbot",
            "atomic_ledger_id": "atomic_ledger_001",
            "requirements": [atomic_requirement()],
            "governance_summary": {"validated": 1, "duplicate": 0},
        },
    ),
    (SchemaTestObligation, obligation_data()),
    (
        SchemaTestObligationLedger,
        {
            "obligation_ledger_id": "obl_ledger_001",
            "project_id": "demo_chatbot",
            "governed_ledger_id": "gov_ledger_001",
            "obligations": [obligation_data()],
        },
    ),
    (ConversationTurn, conversation_turn()),
    (Assertion, assertion()),
    (SchemaTestCase, case_data()),
    (
        DraftTestSuite,
        {
            "draft_suite_id": "draft_suite_001",
            "project_id": "demo_chatbot",
            "obligation_ledger_id": "obl_ledger_001",
            "test_cases": [case_data()],
        },
    ),
    (
        ValidatedTestSuite,
        {
            "validated_suite_id": "validated_suite_001",
            "project_id": "demo_chatbot",
            "draft_suite_id": "draft_suite_001",
            "test_cases": [case_data(status="valid", source_refs=[source_ref()], export_eligible=True)],
            "validation_summary": {"valid": 1, "rejected": 0},
        },
    ),
    (CoverageReport, coverage_report()),
    (
        ReviewReportMetadata,
        {
            "review_report_id": "review_001",
            "project_id": "demo_chatbot",
            "governed_ledger_id": "gov_ledger_001",
            "obligation_ledger_id": "obl_ledger_001",
            "validated_suite_id": "validated_suite_001",
            "coverage_report_id": "coverage_001",
            "report_path": "artifacts/demo_chatbot/run_001/09_review_report/review_report.md",
        },
    ),
    (
        ExecutorExportPackage,
        {
            "export_package_id": "export_001",
            "project_id": "demo_chatbot",
            "validated_suite_id": "validated_suite_001",
            "exported_test_case_ids": ["tc_001"],
            "format": "json",
            "output_paths": ["artifacts/demo_chatbot/run_001/10_executor_export/tests.json"],
            "eligibility_summary": {"eligible": 1, "excluded": 0},
        },
    ),
    (
        SkillDefinition,
        {
            "skill_id": "requirement_extraction_v1",
            "name": "Requirement Extraction",
            "version": "1.0.0",
            "input_contract": "SourcePackage",
            "output_contract": "CandidateRequirementPackage",
            "entrypoint": "skills/requirement_extraction_v1",
        },
    ),
    (
        SkillRunRecord,
        {
            "skill_run_id": "skill_run_001",
            "skill_id": "requirement_extraction_v1",
            "status": "succeeded",
            "input_artifact_paths": ["artifacts/demo_chatbot/run_001/02_source_package/source_package.json"],
            "output_artifact_paths": [
                "artifacts/demo_chatbot/run_001/03_candidate_requirements/candidate_requirement_package.json"
            ],
        },
    ),
    (
        PipelineRunState,
        {
            "pipeline_run_id": "pipeline_001",
            "project_id": "demo_chatbot",
            "run_id": "run_001",
            "status": "running",
            "current_stage": "C07_requirement_extraction",
            "artifact_paths": {
                "source_package": "artifacts/demo_chatbot/run_001/02_source_package/source_package.json"
            },
            "completed_stages": [
                "C03_project_config",
                "C04_document_ingestion",
                "C05_source_ledger",
                "C06_skill_runtime",
            ],
        },
    ),
]


@pytest.mark.parametrize(("model", "data"), CONTRACT_CASES)
def test_each_contract_constructs_and_round_trips(model, data):
    instance = model.from_dict(data)

    assert instance.to_dict() == data
    assert model.from_dict(instance.to_dict()) == instance


def test_golden_schema_fixtures_round_trip():
    fixtures = json.loads((GOLDEN_DIR / "valid_contracts.json").read_text())

    assert ProjectConfig.from_dict(fixtures["ProjectConfig"]).to_dict() == fixtures["ProjectConfig"]
    assert SourceChunk.from_dict(fixtures["SourceChunk"]).to_dict() == fixtures["SourceChunk"]
    assert AtomicRequirement.from_dict(fixtures["AtomicRequirement"]).to_dict() == fixtures["AtomicRequirement"]
    assert SchemaTestObligation.from_dict(fixtures["TestObligation"]).to_dict() == fixtures["TestObligation"]
    assert SchemaTestCase.from_dict(fixtures["TestCase"]).to_dict() == fixtures["TestCase"]
    assert CoverageReport.from_dict(fixtures["CoverageReport"]).to_dict() == fixtures["CoverageReport"]


def test_from_dict_rejects_missing_required_fields_unknown_fields_and_wrong_shapes():
    data = dict(CONTRACT_CASES[0][1])
    data.pop("project_id")
    with pytest.raises(SchemaValidationError, match="project_id"):
        ProjectConfig.from_dict(data)

    data = dict(CONTRACT_CASES[0][1], surprise=True)
    with pytest.raises(SchemaValidationError, match="Unknown field"):
        ProjectConfig.from_dict(data)

    with pytest.raises(SchemaValidationError, match="mapping"):
        ProjectConfig.from_dict(["not", "a", "mapping"])


def test_required_string_ids_must_be_non_empty():
    data = source_chunk()
    data["chunk_id"] = ""

    with pytest.raises(SchemaValidationError, match="chunk_id"):
        SourceChunk.from_dict(data)


def test_enum_fields_reject_unknown_values():
    data = source_chunk()
    data["processing_status"] = "processed"
    with pytest.raises(SchemaValidationError, match="processing_status"):
        SourceChunk.from_dict(data)

    data = atomic_requirement(status="assumption")
    with pytest.raises(SchemaValidationError, match="status"):
        AtomicRequirement.from_dict(data)

    data = case_data(status="ready")
    with pytest.raises(SchemaValidationError, match="status"):
        SchemaTestCase.from_dict(data)


def test_candidate_requirement_confidence_bounds_and_source_refs():
    for confidence in (-0.01, 1.01):
        data = candidate_requirement()
        data["confidence"] = confidence
        with pytest.raises(SchemaValidationError, match="confidence"):
            CandidateRequirement.from_dict(data)

    data = candidate_requirement()
    data["source_refs"] = []
    with pytest.raises(SchemaValidationError, match="source_refs"):
        CandidateRequirement.from_dict(data)


def test_chunk_extraction_result_rejects_not_processed_status():
    with pytest.raises(SchemaValidationError, match="processing_status"):
        ChunkExtractionResult.from_dict(
            {
                "chunk_id": "chunk_001",
                "processing_status": "not_processed",
                "candidate_ids": [],
            }
        )


def test_atomic_requirement_origin_status_and_source_ref_rules():
    data = atomic_requirement(status="inferred", origin="source_derived")
    with pytest.raises(SchemaValidationError, match="origin"):
        AtomicRequirement.from_dict(data)

    data = atomic_requirement(origin="source_derived")
    data.pop("source_refs")
    with pytest.raises(SchemaValidationError, match="source_refs"):
        AtomicRequirement.from_dict(data)

    data = atomic_requirement(origin="source_derived")
    data.pop("candidate_ids")
    with pytest.raises(SchemaValidationError, match="candidate_ids"):
        AtomicRequirement.from_dict(data)

    data = atomic_requirement(origin="assumption")
    data.pop("source_refs")
    with pytest.raises(SchemaValidationError, match="approval_required"):
        AtomicRequirement.from_dict(data)

    req = AtomicRequirement.from_dict(
        atomic_requirement(
            status="validated",
            origin="assumption",
            source_refs=[],
            approval_required=True,
            approval_status="approved",
        )
    )

    assert req.requires_approval_before_export is True


@pytest.mark.parametrize("origin", ["inferred", "assumption", "user_added", "system_default"])
def test_non_source_requirement_origins_are_approval_gated(origin):
    data = atomic_requirement(
        status="validated",
        origin=origin,
        source_refs=[],
        approval_required=True,
        approval_status="approved",
    )

    req = AtomicRequirement.from_dict(data)

    assert req.requires_approval_before_export is True


def test_test_case_requires_requirement_and_obligation_ids():
    data = case_data()
    data["requirement_ids"] = []
    with pytest.raises(SchemaValidationError, match="requirement_ids"):
        SchemaTestCase.from_dict(data)

    data = case_data()
    data["obligation_ids"] = []
    with pytest.raises(SchemaValidationError, match="obligation_ids"):
        SchemaTestCase.from_dict(data)


def test_test_case_source_refs_gate_valid_approved_and_exported_statuses():
    for status in ("valid", "approved", "exported"):
        data = case_data(status=status)
        with pytest.raises(SchemaValidationError, match="source_refs"):
            SchemaTestCase.from_dict(data)

    draft = SchemaTestCase.from_dict(case_data(status="draft"))
    approved = SchemaTestCase.from_dict(
        case_data(status="approved", source_refs=[source_ref()], export_eligible=True)
    )

    assert draft.is_exportable is False
    assert approved.is_exportable is True


def test_coverage_report_rejects_negative_counts():
    data = coverage_report()
    data["requirement_counts"]["uncovered"] = -1

    with pytest.raises(SchemaValidationError, match="requirement_counts"):
        CoverageReport.from_dict(data)


def test_duplicate_ids_are_rejected_in_packages_and_ledgers():
    duplicate_candidate = candidate_requirement()
    package = {
        "candidate_package_id": "cand_pkg_001",
        "project_id": "demo_chatbot",
        "source_package_id": "source_pkg_001",
        "candidates": [candidate_requirement(), duplicate_candidate],
    }
    with pytest.raises(SchemaValidationError, match="candidate_id"):
        CandidateRequirementPackage.from_dict(package)

    ledger = {
        "atomic_ledger_id": "atomic_ledger_001",
        "project_id": "demo_chatbot",
        "candidate_package_id": "cand_pkg_001",
        "requirements": [atomic_requirement(), atomic_requirement()],
    }
    with pytest.raises(SchemaValidationError, match="requirement_id"):
        AtomicRequirementLedger.from_dict(ledger)

    test_case_with_duplicate_turns = case_data(turns=[conversation_turn(), conversation_turn()])
    with pytest.raises(SchemaValidationError, match="turn_id"):
        SchemaTestCase.from_dict(test_case_with_duplicate_turns)


def test_source_package_validates_chunks_against_declared_documents():
    data = {
        "source_package_id": "source_pkg_001",
        "project_id": "demo_chatbot",
        "document_ids": ["doc_001"],
        "chunks": [source_chunk() | {"document_id": "doc_missing"}],
        "checksum": "sha256:pkg001",
    }

    with pytest.raises(SchemaValidationError, match="document_ids"):
        SourcePackage.from_dict(data)


def test_cross_artifact_obligation_validation_rejects_unknown_rejected_and_conflicting_links():
    valid_requirement = AtomicRequirement.from_dict(atomic_requirement())
    rejected_requirement = AtomicRequirement.from_dict(
        atomic_requirement(requirement_id="req_rejected", status="rejected")
    )
    conflicting_requirement = AtomicRequirement.from_dict(
        atomic_requirement(requirement_id="req_conflicting", status="conflicting")
    )

    with pytest.raises(SchemaValidationError, match="unknown requirement"):
        validate_obligation_links(
            [SchemaTestObligation.from_dict(obligation_data(requirement_id="req_missing"))],
            [valid_requirement],
        )

    with pytest.raises(SchemaValidationError, match="rejected"):
        validate_obligation_links(
            [SchemaTestObligation.from_dict(obligation_data(requirement_id="req_rejected"))],
            [rejected_requirement],
        )

    with pytest.raises(SchemaValidationError, match="conflicting"):
        validate_obligation_links(
            [SchemaTestObligation.from_dict(obligation_data(requirement_id="req_conflicting"))],
            [conflicting_requirement],
        )


def test_obligation_validation_rejects_any_obligation_for_rejected_requirements():
    rejected_requirement = AtomicRequirement.from_dict(
        atomic_requirement(requirement_id="req_rejected", status="rejected")
    )

    for status in ("planned", "rejected"):
        with pytest.raises(SchemaValidationError, match="rejected"):
            validate_obligation_links(
                [
                    SchemaTestObligation.from_dict(
                        obligation_data(requirement_id="req_rejected", status=status)
                    )
                ],
                [rejected_requirement],
            )


def test_obligation_validation_allows_non_rejected_requirements_with_matching_source_refs():
    requirement = AtomicRequirement.from_dict(atomic_requirement())
    obligation = SchemaTestObligation.from_dict(obligation_data())

    validate_obligation_links([obligation], [requirement])


def test_obligation_source_refs_must_match_linked_requirement_source_refs():
    requirement = AtomicRequirement.from_dict(atomic_requirement())

    invalid_obligations = [
        obligation_data(source_refs=[]),
        obligation_data(source_refs=[{"document_id": "doc_002", "chunk_id": "chunk_001"}]),
        obligation_data(source_refs=[{"document_id": "doc_001", "chunk_id": "chunk_002"}]),
    ]

    for obligation in invalid_obligations:
        with pytest.raises(SchemaValidationError, match="source_refs"):
            validate_obligation_links(
                [SchemaTestObligation.from_dict(obligation)],
                [requirement],
            )


def test_obligation_validation_rejects_invented_source_refs_for_non_source_requirement():
    obligation = SchemaTestObligation.from_dict(obligation_data())

    omitted_source_refs = atomic_requirement(
        origin="assumption",
        approval_required=True,
        approval_status="approved",
    )
    omitted_source_refs.pop("source_refs")
    empty_source_refs = atomic_requirement(
        origin="assumption",
        source_refs=[],
        approval_required=True,
        approval_status="approved",
    )

    for requirement_data in (omitted_source_refs, empty_source_refs):
        requirement = AtomicRequirement.from_dict(requirement_data)
        with pytest.raises(SchemaValidationError, match="source_refs"):
            validate_obligation_links([obligation], [requirement])


def test_obligation_source_refs_match_order_insensitively_after_normalization():
    refs = [
        {"document_id": "doc_001", "chunk_id": "chunk_001", "location": "requirements.md:1"},
        {"document_id": "doc_002", "chunk_id": "chunk_002"},
    ]
    requirement = AtomicRequirement.from_dict(atomic_requirement(source_refs=refs))
    obligation = SchemaTestObligation.from_dict(obligation_data(source_refs=list(reversed(refs))))

    validate_obligation_links([obligation], [requirement])


def test_cross_artifact_test_case_validation_rejects_unknown_and_conflicting_links():
    requirement = AtomicRequirement.from_dict(atomic_requirement())
    conflicting_requirement = AtomicRequirement.from_dict(
        atomic_requirement(requirement_id="req_conflicting", status="conflicting")
    )
    obligation = SchemaTestObligation.from_dict(obligation_data())

    with pytest.raises(SchemaValidationError, match="unknown requirement"):
        validate_test_case_links(
            [SchemaTestCase.from_dict(case_data(requirement_ids=["req_missing"]))],
            [requirement],
            [obligation],
        )

    with pytest.raises(SchemaValidationError, match="unknown obligation"):
        validate_test_case_links(
            [SchemaTestCase.from_dict(case_data(obligation_ids=["obl_missing"]))],
            [requirement],
            [obligation],
        )

    with pytest.raises(SchemaValidationError, match="conflicting"):
        validate_test_case_links(
            [
                SchemaTestCase.from_dict(
                    case_data(
                        status="approved",
                        requirement_ids=["req_conflicting"],
                        source_refs=[source_ref()],
                        export_eligible=True,
                    )
                )
            ],
            [conflicting_requirement],
            [obligation],
        )


def test_executor_export_package_validation_rejects_ineligible_tests():
    source = SchemaTestCase.from_dict(case_data(status="draft"))
    suite = ValidatedTestSuite.from_dict(
        {
            "validated_suite_id": "validated_suite_001",
            "project_id": "demo_chatbot",
            "draft_suite_id": "draft_suite_001",
            "test_cases": [source.to_dict()],
            "validation_summary": {"draft": 1},
        }
    )
    package = ExecutorExportPackage.from_dict(CONTRACT_CASES[20][1])

    with pytest.raises(SchemaValidationError, match="not exportable"):
        validate_executor_export_package(package, suite)

    valid_test = SchemaTestCase.from_dict(
        case_data(status="approved", source_refs=[source_ref()], export_eligible=True)
    )
    valid_suite = ValidatedTestSuite.from_dict(
        {
            "validated_suite_id": "validated_suite_001",
            "project_id": "demo_chatbot",
            "draft_suite_id": "draft_suite_001",
            "test_cases": [valid_test.to_dict()],
            "validation_summary": {"approved": 1},
        }
    )

    validate_executor_export_package(package, valid_suite)


def test_serialization_returns_json_compatible_data_without_mutating_input():
    data = atomic_requirement()
    original = copy.deepcopy(data)

    instance = AtomicRequirement.from_dict(data)
    encoded = json.loads(json.dumps(instance.to_dict()))

    assert encoded == original
    assert data == original
