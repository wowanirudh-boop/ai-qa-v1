import json
from pathlib import Path

from ai_testgen.coverage import build_coverage_report


def source_ref(chunk_id: str = "chunk_001", document_id: str = "doc_001") -> dict:
    return {"document_id": document_id, "chunk_id": chunk_id}


def source_chunk(**overrides: object) -> dict:
    data = {
        "chunk_id": "chunk_001",
        "document_id": "doc_001",
        "text": "The bot must ask for an order number before showing order status.",
        "checksum": "sha256:chunk001",
        "processing_status": "requirements_extracted",
    }
    data.update(overrides)
    return data


def source_package_data(**overrides: object) -> dict:
    data = {
        "source_package_id": "source_pkg_001",
        "project_id": "demo_chatbot",
        "document_ids": ["doc_001"],
        "chunks": [
            source_chunk(),
            source_chunk(
                chunk_id="chunk_002",
                text="The bot must explain refund timing.",
                checksum="sha256:chunk002",
            ),
            source_chunk(
                chunk_id="chunk_003",
                text="Background support policy context.",
                checksum="sha256:chunk003",
                processing_status="non_testable_context",
            ),
        ],
        "checksum": "sha256:pkg001",
    }
    data.update(overrides)
    return data


def governed_requirement(**overrides: object) -> dict:
    data = {
        "requirement_id": "req_001",
        "statement": "The bot must ask for an order number before showing order status.",
        "requirement_type": "functional",
        "status": "validated",
        "origin": "source_derived",
        "source_refs": [source_ref()],
        "candidate_ids": ["cand_001"],
    }
    data.update(overrides)
    return data


def governed_ledger_data(**overrides: object) -> dict:
    data = {
        "governed_ledger_id": "gov_ledger_001",
        "project_id": "demo_chatbot",
        "atomic_ledger_id": "atomic_ledger_001",
        "requirements": [
            governed_requirement(),
            governed_requirement(
                requirement_id="req_002",
                statement="The bot must explain refund timing.",
                source_refs=[source_ref(chunk_id="chunk_002")],
                candidate_ids=["cand_002"],
            ),
        ],
        "governance_summary": {
            "conflicting": 0,
            "duplicate": 0,
            "inferred": 0,
            "needs_clarification": 0,
            "out_of_scope": 0,
            "rejected": 0,
            "validated": 2,
        },
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


def obligation_ledger_data(**overrides: object) -> dict:
    data = {
        "obligation_ledger_id": "obl_ledger_001",
        "project_id": "demo_chatbot",
        "governed_ledger_id": "gov_ledger_001",
        "obligations": [
            obligation_data(),
            obligation_data(
                obligation_id="obl_002",
                requirement_id="req_002",
                obligation_type="positive",
                status="planned",
                source_refs=[source_ref(chunk_id="chunk_002")],
            ),
            obligation_data(
                obligation_id="obl_003",
                requirement_id="req_002",
                obligation_type="blocked_conflict",
                status="blocked_unclear_requirement",
                source_refs=[source_ref(chunk_id="chunk_002")],
            ),
        ],
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
        "expected": "The bot asks for the order number before providing status.",
    }


def validated_test_case_data(**overrides: object) -> dict:
    data = {
        "test_case_id": "tc_001",
        "title": "Order status requires order number",
        "status": "valid",
        "requirement_ids": ["req_001"],
        "obligation_ids": ["obl_001"],
        "source_refs": [source_ref()],
        "turns": [conversation_turn()],
        "assertions": [assertion()],
        "export_eligible": True,
    }
    data.update(overrides)
    return data


def validated_suite_data(**overrides: object) -> dict:
    data = {
        "validated_suite_id": "validated_suite_001",
        "project_id": "demo_chatbot",
        "draft_suite_id": "draft_suite_001",
        "test_cases": [validated_test_case_data()],
        "validation_summary": {
            "valid": 1,
            "needs_review": 0,
            "rejected": 0,
            "export_eligible": 1,
        },
    }
    data.update(overrides)
    return data


def test_coverage_counts_requirements_obligations_tests_and_source_chunks():
    report = build_coverage_report(
        validated_suite_data(),
        governed_ledger_data(),
        obligation_ledger_data(),
        source_package_data(),
    )

    assert report.to_dict() == {
        "coverage_report_id": "coverage_001",
        "project_id": "demo_chatbot",
        "validated_suite_id": "validated_suite_001",
        "requirement_counts": {
            "total": 2,
            "covered": 1,
            "uncovered": 1,
        },
        "obligation_counts": {
            "total": 3,
            "covered": 1,
            "uncovered": 1,
            "blocked": 1,
            "skipped": 0,
        },
        "test_counts": {
            "total": 1,
            "valid": 1,
            "needs_review": 0,
            "export_eligible": 1,
            "rejected": 0,
        },
        "source_chunk_counts": {
            "total": 3,
            "with_requirements": 2,
            "covered": 1,
            "uncovered": 1,
            "without_requirements": 1,
        },
        "uncovered_requirement_ids": ["req_002"],
        "uncovered_obligation_ids": ["obl_002"],
    }


def test_coverage_counts_are_zero_or_positive_with_empty_inputs():
    report = build_coverage_report(
        validated_suite_data(test_cases=[], validation_summary={}),
        governed_ledger_data(requirements=[], governance_summary={}),
        obligation_ledger_data(obligations=[]),
        None,
    )

    data = report.to_dict()

    for count_map in (
        data["requirement_counts"],
        data["obligation_counts"],
        data["test_counts"],
        data["source_chunk_counts"],
    ):
        assert all(value >= 0 for value in count_map.values())


def test_coverage_report_round_trips_golden_fixture():
    golden_dir = Path(__file__).parent / "fixtures" / "golden" / "test_validation_coverage"
    expected = json.loads((golden_dir / "coverage_report.json").read_text(encoding="utf-8"))

    report = build_coverage_report(
        json.loads((golden_dir / "validated_test_suite.json").read_text(encoding="utf-8")),
        json.loads((golden_dir / "governed_requirement_ledger.json").read_text(encoding="utf-8")),
        json.loads((golden_dir / "test_obligation_ledger.json").read_text(encoding="utf-8")),
        json.loads((golden_dir / "source_package.json").read_text(encoding="utf-8")),
    )

    assert report.to_dict() == expected
