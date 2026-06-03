import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_testgen.cli as cli
import ai_testgen.obligation_planning as obligation_planning
from ai_testgen.artifact_store import ArtifactStore
from ai_testgen.obligation_planning import (
    GovernedLedgerArtifactError,
    InvalidTestObligationLedgerError,
    ProjectConfigArtifactError,
    plan_obligations_from_governed_ledger_artifact,
    plan_test_obligations,
)
from ai_testgen.schemas import (
    GovernedRequirementLedger,
    ProjectConfig,
    TestObligationStatus,
    TestObligationLedger as SchemaTestObligationLedger,
)


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "obligation_planning"


def source_ref(chunk_id: str = "chunk_001", document_id: str = "doc_001") -> dict:
    return {"document_id": document_id, "chunk_id": chunk_id}


def project_config_data(**overrides: object) -> dict:
    data = {
        "project_id": "demo_chatbot",
        "bot_name": "Demo Support Bot",
        "target_url": "https://example.test/chat",
        "coverage_policy": {
            "require_negative_tests": True,
            "require_positive_tests": True,
        },
        "approval_policy": {
            "allow_export_without_review": False,
            "require_human_approval_for_inferred": True,
        },
    }
    data.update(overrides)
    return data


def governed_requirement(**overrides: object) -> dict:
    data = {
        "requirement_id": "req_001",
        "statement": "The bot must ask for a booking reference before showing appointment details.",
        "requirement_type": "functional",
        "status": "validated",
        "origin": "source_derived",
        "source_refs": [source_ref()],
        "candidate_ids": ["cand_001"],
        "metadata": {
            "required_entity": "booking_reference",
            "collection_mode": "chatbot_collects",
        },
    }
    data.update(overrides)
    return data


def governed_ledger_data(**overrides: object) -> dict:
    data = {
        "governed_ledger_id": "gov_ledger_001",
        "project_id": "demo_chatbot",
        "atomic_ledger_id": "atomic_ledger_001",
        "requirements": [governed_requirement()],
        "governance_summary": {
            "conflicting": 0,
            "duplicate": 0,
            "inferred": 0,
            "needs_clarification": 0,
            "out_of_scope": 0,
            "rejected": 0,
            "validated": 1,
        },
    }
    data.update(overrides)
    return data


def stable_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def obligation_types_for_requirement(obligation_ledger, requirement_id: str) -> list[str]:
    return [
        obligation.obligation_type
        for obligation in obligation_ledger.obligations
        if obligation.requirement_id == requirement_id
    ]


def write_project_config(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "00_project_config",
        "project_config",
        data or project_config_data(),
    )


def write_governed_ledger(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "05_governed_requirements",
        "governed_requirement_ledger",
        data or governed_ledger_data(),
    )


def test_plan_obligations_happy_path_writes_obligation_ledger(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_project_config(store)
    governed_artifact = write_governed_ledger(store)

    result = plan_obligations_from_governed_ledger_artifact(governed_artifact.path)

    expected_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "06_test_obligations"
        / "test_obligation_ledger.json"
    )
    assert result.obligation_ledger_path == expected_path
    assert result.obligation_ledger.to_dict() == {
        "obligation_ledger_id": "obl_ledger_001",
        "project_id": "demo_chatbot",
        "governed_ledger_id": "gov_ledger_001",
        "obligations": [
            {
                "obligation_id": "obl_001",
                "requirement_id": "req_001",
                "obligation_type": "missing_entity",
                "status": "planned",
                "source_refs": [source_ref()],
                "description": (
                    "Verify the chatbot asks for the required entity before continuing: "
                    "The bot must ask for a booking reference before showing appointment details."
                ),
                "coverage_intent": "Exercise the documented missing-entity branch without inventing a generic negative case.",
                "metadata": {
                    "chatbot_obligation": True,
                    "planning_rule": "missing_entity_requirement",
                    "source_supported_negative": True,
                },
            },
            {
                "obligation_id": "obl_002",
                "requirement_id": "req_001",
                "obligation_type": "provided_entity",
                "status": "planned",
                "source_refs": [source_ref()],
                "description": (
                    "Verify the chatbot proceeds when the required entity is provided: "
                    "The bot must ask for a booking reference before showing appointment details."
                ),
                "coverage_intent": "Exercise the documented provided-entity path for the chatbot flow.",
                "metadata": {
                    "chatbot_obligation": True,
                    "planning_rule": "functional_provided_entity",
                },
            },
        ],
        "coverage_policy_snapshot": {
            "require_negative_tests": True,
            "require_positive_tests": True,
        },
    }
    assert SchemaTestObligationLedger.from_dict(
        json.loads(expected_path.read_text(encoding="utf-8"))
    ) == result.obligation_ledger


def test_validated_requirement_becomes_planned_obligations():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(governed_ledger_data())

    obligation_ledger = plan_test_obligations(governed, config)

    assert [obligation.obligation_type for obligation in obligation_ledger.obligations] == [
        "missing_entity",
        "provided_entity",
    ]
    assert [obligation.status for obligation in obligation_ledger.obligations] == [
        "planned",
        "planned",
    ]


def test_rejected_requirement_creates_no_obligation():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(status="rejected", rationale="Out of scope."),
            ],
            governance_summary={
                "conflicting": 0,
                "duplicate": 0,
                "inferred": 0,
                "needs_clarification": 0,
                "out_of_scope": 0,
                "rejected": 1,
                "validated": 0,
            },
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert obligation_ledger.obligations == []


def test_conflicting_requirement_creates_only_blocked_non_normal_obligation():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_001",
                    status="validated",
                ),
                governed_requirement(
                    requirement_id="req_002",
                    statement="The bot must show appointment details without asking for a booking reference.",
                    status="conflicting",
                    conflicts_with=["req_001"],
                    source_refs=[source_ref(chunk_id="chunk_002")],
                    candidate_ids=["cand_002"],
                ),
            ],
            governance_summary={
                "conflicting": 1,
                "duplicate": 0,
                "inferred": 0,
                "needs_clarification": 0,
                "out_of_scope": 0,
                "rejected": 0,
                "validated": 1,
            },
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)
    conflict_obligations = [
        obligation
        for obligation in obligation_ledger.obligations
        if obligation.requirement_id == "req_002"
    ]

    assert len(conflict_obligations) == 1
    assert conflict_obligations[0].obligation_type == "blocked_conflict"
    assert conflict_obligations[0].status == "blocked_unclear_requirement"
    assert conflict_obligations[0].blocked_reason == (
        "Conflicting requirement must be resolved before normal obligations can be planned."
    )


def test_obligation_inherits_source_refs_from_requirement():
    refs = [
        {"document_id": "doc_001", "chunk_id": "chunk_001", "location": "requirements.md:1"},
        {"document_id": "doc_002", "chunk_id": "chunk_002"},
    ]
    config = ProjectConfig.from_dict(project_config_data(coverage_policy={"require_positive_tests": True}))
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(requirements=[governed_requirement(source_refs=refs)])
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert obligation_ledger.obligations[0].source_refs == governed.requirements[0].source_refs


def test_coverage_policy_affects_obligation_type():
    config = ProjectConfig.from_dict(
        project_config_data(
            coverage_policy={
                "require_negative_tests": False,
                "require_positive_tests": True,
            }
        )
    )
    governed = GovernedRequirementLedger.from_dict(governed_ledger_data())

    obligation_ledger = plan_test_obligations(governed, config)

    assert [obligation.obligation_type for obligation in obligation_ledger.obligations] == [
        "provided_entity"
    ]
    assert obligation_ledger.obligations[0].status == "planned"


def test_entity_collection_mapping_uses_requirement_type_and_policy():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_type="entity_collection",
                    statement="The bot must collect an appointment date before checking availability.",
                    metadata={
                        "required_entity": "appointment_date",
                        "collection_mode": "chatbot_collects",
                        "entity_format": "ISO date",
                    },
                )
            ]
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert [obligation.obligation_type for obligation in obligation_ledger.obligations] == [
        "missing_entity",
        "provided_entity",
        "invalid_entity",
    ]
    assert all(obligation.description for obligation in obligation_ledger.obligations)
    assert all(obligation.coverage_intent for obligation in obligation_ledger.obligations)


def test_api_schema_only_requirement_is_skipped_not_planned_chatbot_obligation():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_schema",
                    requirement_type="response_contract",
                    statement="The backend API response schema includes accountId and planType fields.",
                    metadata={"backend_only": True, "api_schema_only": True},
                )
            ]
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert len(obligation_ledger.obligations) == 1
    obligation = obligation_ledger.obligations[0]
    assert obligation.obligation_type == "non_chatbot_api_schema"
    assert obligation.status == TestObligationStatus.SKIPPED_BY_POLICY
    assert obligation.metadata == {
        "chatbot_obligation": False,
        "planning_rule": "api_schema_only_requirement",
    }
    assert obligation.blocked_reason == (
        "API-schema-only requirement is not a chatbot test obligation by default."
    )


def test_generic_positive_negative_obligations_are_not_created_for_every_requirement():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_prompt",
                    requirement_type="intent_handling",
                    statement=(
                        "When the user intent is \"Check Appointments\", the bot must open the appointment lookup flow."
                    ),
                    metadata={},
                ),
                governed_requirement(
                    requirement_id="req_schema",
                    requirement_type="response_field",
                    statement="The backend API response data object includes accountId and planType fields.",
                    source_refs=[source_ref(chunk_id="chunk_002")],
                    candidate_ids=["cand_002"],
                    metadata={"backend_only": True},
                ),
            ],
            governance_summary={
                "conflicting": 0,
                "duplicate": 0,
                "inferred": 0,
                "needs_clarification": 0,
                "out_of_scope": 0,
                "rejected": 0,
                "validated": 2,
            },
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert obligation_types_for_requirement(obligation_ledger, "req_prompt") == ["global_intent"]
    assert obligation_types_for_requirement(obligation_ledger, "req_schema") == ["non_chatbot_api_schema"]
    assert "positive" not in [obligation.obligation_type for obligation in obligation_ledger.obligations]
    assert "negative" not in [obligation.obligation_type for obligation in obligation_ledger.obligations]


def test_negative_obligation_is_created_for_documented_validation_condition():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_type="validation_constraint",
                    statement=(
                        "The account code input must contain numbers only, with no spaces or dashes."
                    ),
                    metadata={},
                )
            ]
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert [obligation.obligation_type for obligation in obligation_ledger.obligations] == ["invalid_entity"]
    assert obligation_ledger.obligations[0].metadata["source_supported_negative"] is True


def test_non_order_entity_collection_metadata_produces_chatbot_obligations():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_collect_claim_number",
                    requirement_type="entity_collection",
                    statement="The bot must collect a claim number before showing claim details.",
                    metadata={
                        "required_entity": "claim_number",
                        "collection_mode": "chatbot_collects",
                        "entity_format": "three letters followed by six digits",
                    },
                ),
                governed_requirement(
                    requirement_id="req_collect_booking_reference",
                    requirement_type="functional",
                    statement="The chatbot must ask for a booking reference before retrieving an appointment.",
                    source_refs=[source_ref(chunk_id="chunk_002")],
                    candidate_ids=["cand_002"],
                    metadata={
                        "required_entity": "booking_reference",
                        "collection_mode": "chatbot_collects",
                    },
                ),
            ],
            governance_summary={
                "conflicting": 0,
                "duplicate": 0,
                "inferred": 0,
                "needs_clarification": 0,
                "out_of_scope": 0,
                "rejected": 0,
                "validated": 2,
            },
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert obligation_types_for_requirement(obligation_ledger, "req_collect_claim_number") == [
        "missing_entity",
        "provided_entity",
        "invalid_entity",
    ]
    assert obligation_types_for_requirement(obligation_ledger, "req_collect_booking_reference") == [
        "missing_entity",
        "provided_entity",
    ]
    assert all(
        obligation.status == TestObligationStatus.PLANNED
        for obligation in obligation_ledger.obligations
    )


def test_required_entity_metadata_creates_entity_obligations_without_domain_terms():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_account_recovery",
                    requirement_type="functional",
                    statement="The chatbot must verify the account recovery details before continuing.",
                    metadata={
                        "required_entities": ["account_id", "recovery_email"],
                        "supported_entities": ["account_id", "recovery_email"],
                        "collection_mode": "chatbot_collects",
                        "entity_format": "valid email address for recovery_email",
                    },
                )
            ]
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert obligation_types_for_requirement(obligation_ledger, "req_account_recovery") == [
        "missing_entity",
        "provided_entity",
        "invalid_entity",
    ]


def test_order_id_collection_is_allowed_when_source_supported():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_source_supported_order_id",
                    requirement_type="functional",
                    statement="The chatbot must ask for Order ID before checking self-service order updates.",
                    source_refs=[
                        source_ref(
                            chunk_id="chunk_order",
                            document_id="doc_order",
                        )
                    ],
                    candidate_ids=["cand_order"],
                    metadata={
                        "required_entity": "Order ID",
                        "collection_mode": "chatbot_collects",
                        "supported_entities": ["Order ID"],
                    },
                )
            ]
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert obligation_types_for_requirement(obligation_ledger, "req_source_supported_order_id") == [
        "missing_entity",
        "provided_entity",
    ]


def test_phone_is_not_globally_required_without_collection_support():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_phone_faq",
                    requirement_type="functional",
                    statement="The chatbot should answer whether users can update a phone number in profile settings.",
                    metadata={},
                )
            ]
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert obligation_types_for_requirement(obligation_ledger, "req_phone_faq") == [
        "skipped_by_policy"
    ]


def test_phone_collection_does_not_imply_ten_digit_validation():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_callback_phone",
                    requirement_type="entity_collection",
                    statement="The chatbot must collect a callback phone number for follow-up.",
                    metadata={
                        "required_entity": "callback_phone",
                        "collection_mode": "chatbot_collects",
                    },
                )
            ]
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert obligation_types_for_requirement(obligation_ledger, "req_callback_phone") == [
        "missing_entity",
        "provided_entity",
    ]
    assert "invalid_entity" not in obligation_types_for_requirement(
        obligation_ledger,
        "req_callback_phone",
    )
    assert "10" not in json.dumps(obligation_ledger.to_dict())


def test_user_facing_status_response_is_not_treated_as_api_schema_only():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_claim_status",
                    requirement_type="response_field",
                    statement="The chatbot should tell the user the claim status after lookup.",
                    metadata={"documents_user_facing_bot_behavior": True},
                )
            ]
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert obligation_types_for_requirement(obligation_ledger, "req_claim_status") == ["api_success"]


def test_non_order_api_schema_metadata_is_skipped_by_policy():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_claim_schema",
                    requirement_type="response_contract",
                    statement=(
                        "The backend API response schema includes accountId, claimStatus, "
                        "createdAt, amount, and planType fields."
                    ),
                    metadata={
                        "backend_only": True,
                        "api_contract": True,
                        "response_field": "claimStatus",
                        "field_type": "string",
                        "nullability": "non_null",
                    },
                )
            ]
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert obligation_types_for_requirement(obligation_ledger, "req_claim_schema") == [
        "non_chatbot_api_schema"
    ]
    assert obligation_ledger.obligations[0].status == TestObligationStatus.SKIPPED_BY_POLICY


def test_api_error_mapping_requires_documented_user_facing_bot_behavior():
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_user_facing_error",
                    requirement_type="error_response_mapping",
                    statement=(
                        "When no matching claim is found with HTTP 404 and error code "
                        "ERR_CLAIM_NOT_FOUND, the chatbot standardized output must be "
                        "\"I could not find that claim.\""
                    ),
                    metadata={"documented_errors": ["claim_not_found"]},
                ),
                governed_requirement(
                    requirement_id="req_raw_error",
                    requirement_type="api_error_handling",
                    statement="HTTP 500 with error code ERR_INTERNAL means an upstream service failure occurred.",
                    source_refs=[source_ref(chunk_id="chunk_002")],
                    candidate_ids=["cand_002"],
                    metadata={"backend_only": True},
                ),
            ],
            governance_summary={
                "conflicting": 0,
                "duplicate": 0,
                "inferred": 0,
                "needs_clarification": 0,
                "out_of_scope": 0,
                "rejected": 0,
                "validated": 2,
            },
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert obligation_types_for_requirement(obligation_ledger, "req_user_facing_error") == ["api_error"]
    assert obligation_types_for_requirement(obligation_ledger, "req_raw_error") == [
        "non_chatbot_api_schema"
    ]


def test_planned_obligations_preserve_requirement_ids_and_source_refs():
    refs = [
        {"document_id": "doc_001", "chunk_id": "chunk_001", "location": "requirements.md:1"},
    ]
    config = ProjectConfig.from_dict(project_config_data())
    governed = GovernedRequirementLedger.from_dict(
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_error",
                    requirement_type="api_error_handling",
                    statement=(
                        "If the appointment lookup API returns 429, the bot must respond with "
                        "\"I'm having trouble connecting to our system right now.\""
                    ),
                    source_refs=refs,
                    metadata={"documented_errors": ["rate_limit"]},
                )
            ]
        )
    )

    obligation_ledger = plan_test_obligations(governed, config)

    assert len(obligation_ledger.obligations) == 1
    assert obligation_ledger.obligations[0].requirement_id == "req_error"
    assert obligation_ledger.obligations[0].source_refs == governed.requirements[0].source_refs


def test_policy_that_requires_no_obligation_types_creates_skipped_obligation():
    config = ProjectConfig.from_dict(
        project_config_data(
            coverage_policy={
                "require_negative_tests": False,
                "require_positive_tests": False,
            }
        )
    )
    governed = GovernedRequirementLedger.from_dict(governed_ledger_data())

    obligation_ledger = plan_test_obligations(governed, config)

    assert len(obligation_ledger.obligations) == 1
    assert obligation_ledger.obligations[0].obligation_type == "skipped_by_policy"
    assert obligation_ledger.obligations[0].status == "skipped_by_policy"
    assert obligation_ledger.obligations[0].blocked_reason == (
        "Coverage policy does not require obligations for this requirement."
    )


def test_invalid_coverage_policy_flag_is_reported():
    config = ProjectConfig.from_dict(
        project_config_data(coverage_policy={"require_positive_tests": "yes"})
    )
    governed = GovernedRequirementLedger.from_dict(governed_ledger_data())

    with pytest.raises(InvalidTestObligationLedgerError, match="require_positive_tests"):
        plan_test_obligations(governed, config)


def test_project_config_mismatch_is_rejected():
    config = ProjectConfig.from_dict(project_config_data(project_id="other_project"))
    governed = GovernedRequirementLedger.from_dict(governed_ledger_data())

    with pytest.raises(InvalidTestObligationLedgerError, match="project_id"):
        plan_test_obligations(governed, config)


def test_missing_project_config_artifact_is_reported(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    governed_artifact = write_governed_ledger(store)

    with pytest.raises(ProjectConfigArtifactError, match="ProjectConfig"):
        plan_obligations_from_governed_ledger_artifact(governed_artifact.path)

    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "06_test_obligations"
        / "test_obligation_ledger.json"
    ).exists()


def test_governed_ledger_artifact_path_must_match_c10_input_convention(tmp_path):
    invalid_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "wrong"
        / "governed_requirement_ledger.json"
    )

    with pytest.raises(GovernedLedgerArtifactError, match="05_governed_requirements"):
        plan_obligations_from_governed_ledger_artifact(invalid_path)


def test_golden_fixture_governed_ledger_to_obligation_ledger(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    project_config = json.loads((GOLDEN_DIR / "project_config.json").read_text(encoding="utf-8"))
    governed_ledger = json.loads((GOLDEN_DIR / "governed_requirement_ledger.json").read_text(encoding="utf-8"))
    expected_obligations = json.loads((GOLDEN_DIR / "test_obligation_ledger.json").read_text(encoding="utf-8"))
    write_project_config(store, data=project_config)
    governed_artifact = write_governed_ledger(store, data=governed_ledger)

    result = plan_obligations_from_governed_ledger_artifact(governed_artifact.path)

    assert result.obligation_ledger.to_dict() == expected_obligations
    assert stable_json(result.obligation_ledger.to_dict()) == (
        GOLDEN_DIR / "test_obligation_ledger.json"
    ).read_text(encoding="utf-8")


def test_cli_plan_obligations_smoke_delegates_to_c10(tmp_path, monkeypatch, capsys):
    governed_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "05_governed_requirements"
        / "governed_requirement_ledger.json"
    )
    obligation_path = tmp_path / "test_obligation_ledger.json"
    calls = []

    def fake_plan(governed_ledger):
        calls.append(governed_ledger)
        return SimpleNamespace(obligation_ledger_path=obligation_path)

    monkeypatch.setattr(cli, "plan_obligations_from_governed_ledger_artifact", fake_plan)

    exit_code = cli.main(["plan-obligations", "--governed-ledger", str(governed_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(obligation_path) in captured.out
    assert captured.err == ""
    assert calls == [governed_path]


def test_cli_plan_obligations_reports_missing_project_config(tmp_path, capsys):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    governed_artifact = write_governed_ledger(store)

    exit_code = cli.main(["plan-obligations", "--governed-ledger", str(governed_artifact.path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "error:" in captured.err
    assert "ProjectConfig" in captured.err


def test_c10_writes_no_future_component_artifacts(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_project_config(store)
    governed_artifact = write_governed_ledger(store)

    plan_obligations_from_governed_ledger_artifact(governed_artifact.path)

    files = sorted(path.relative_to(artifact_root).as_posix() for path in artifact_root.rglob("*") if path.is_file())
    assert files == [
        "demo_chatbot/run_001/00_project_config/project_config.json",
        "demo_chatbot/run_001/05_governed_requirements/governed_requirement_ledger.json",
        "demo_chatbot/run_001/06_test_obligations/test_obligation_ledger.json",
    ]


def test_c10_implementation_has_no_future_component_or_provider_dependencies():
    source = inspect.getsource(obligation_planning)

    for forbidden in (
        "DraftTestSuite",
        "TestCase",
        "ExecutorExportPackage",
        "SkillRuntime",
        "op" + "enai",
        "anth" + "ropic",
        "lang" + "chain",
        "llama" + "_index",
        "req" + "uests",
        "ht" + "tpx",
        "url" + "lib",
        "so" + "cket",
        "sub" + "process",
    ):
        assert forbidden not in source


def test_c10_implementation_has_no_order_tracking_fixture_policy_terms():
    source = inspect.getsource(obligation_planning).lower()

    forbidden_terms = (
        "order",
        "order_id",
        "orderid",
        "order number",
        "tracking",
        "carrier",
        "trackinglink",
        "expecteddeliverydate",
        "registered phone",
        "latest order",
        "no active orders",
        "email address or order id",
        "status value",
        "delivery status",
    )

    assert [term for term in forbidden_terms if term in source] == []
