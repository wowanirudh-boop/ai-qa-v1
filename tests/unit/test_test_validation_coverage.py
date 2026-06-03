import json
from pathlib import Path

from ai_testgen.coverage import build_coverage_report
from ai_testgen.test_validation import validate_draft_suite


def source_ref(chunk_id: str = "chunk_phone", document_id: str = "doc_order") -> dict:
    return {"document_id": document_id, "chunk_id": chunk_id}


def source_chunk(**overrides: object) -> dict:
    data = {
        "chunk_id": "chunk_phone",
        "document_id": "doc_order",
        "text": (
            "When the user wants to track an order, the bot asks for the 10-digit "
            "phone number used during checkout. If the tracking API returns 200 OK, "
            "the bot tells the user the delivery status for the latest active order. "
            "The test fixture registers phone 5551234567 and stubs the order tracking "
            "API to return a SHIPPED status."
        ),
        "checksum": "sha256:chunk-phone",
        "processing_status": "requirements_extracted",
    }
    data.update(overrides)
    return data


def source_package_data(**overrides: object) -> dict:
    data = {
        "source_package_id": "source_pkg_order",
        "project_id": "demo_chatbot",
        "document_ids": ["doc_order"],
        "chunks": [
            source_chunk(),
            source_chunk(
                chunk_id="chunk_api_schema",
                text=(
                    "The API response body contains success, data, orderId, carrier, "
                    "trackingLink, expectedDeliveryDate, status, type, maxLength, "
                    "required, and nullability fields for the API contract."
                ),
                checksum="sha256:chunk-api-schema",
            ),
            source_chunk(
                chunk_id="chunk_agent",
                text=(
                    "If the user does not have the registered phone number, the bot "
                    "directs the user to an agent. The agent can locate the order using "
                    "the user's email address or Order ID."
                ),
                checksum="sha256:chunk-agent",
            ),
        ],
        "checksum": "sha256:source-pkg-order",
    }
    data.update(overrides)
    return data


def governed_requirement(**overrides: object) -> dict:
    data = {
        "requirement_id": "req_phone",
        "statement": (
            "When the user wants to track an order, the bot must ask for the 10-digit "
            "phone number used during checkout and use it for the API-backed status lookup."
        ),
        "requirement_type": "status_response",
        "status": "validated",
        "origin": "source_derived",
        "source_refs": [source_ref()],
        "candidate_ids": ["cand_phone"],
        "metadata": {"chatbot_testable": True},
    }
    data.update(overrides)
    return data


def governed_ledger_data(**overrides: object) -> dict:
    requirements = [
        governed_requirement(),
        governed_requirement(
            requirement_id="req_api_schema",
            statement="The API response data object includes orderId, carrier, status, and trackingLink fields.",
            requirement_type="response_contract",
            source_refs=[source_ref("chunk_api_schema")],
            candidate_ids=["cand_api_schema"],
            metadata={"api_schema_only": True, "chatbot_testable": False},
        ),
        governed_requirement(
            requirement_id="req_agent",
            statement=(
                "When the user lacks the registered phone number, the bot must direct "
                "the user to an agent who can locate the order by email address or Order ID."
            ),
            requirement_type="human_handoff",
            source_refs=[source_ref("chunk_agent")],
            candidate_ids=["cand_agent"],
            metadata={"chatbot_self_service_order_id_supported": False},
        ),
    ]
    data = {
        "governed_ledger_id": "gov_ledger_001",
        "project_id": "demo_chatbot",
        "atomic_ledger_id": "atomic_ledger_001",
        "requirements": requirements,
        "governance_summary": {
            "conflicting": 0,
            "duplicate": 0,
            "inferred": 0,
            "needs_clarification": 0,
            "out_of_scope": 0,
            "rejected": 0,
            "validated": len(requirements),
        },
    }
    data.update(overrides)
    return data


def obligation_data(**overrides: object) -> dict:
    data = {
        "obligation_id": "obl_phone_success",
        "requirement_id": "req_phone",
        "obligation_type": "api_success",
        "status": "planned",
        "description": "Verify successful order tracking after the user provides a valid 10-digit phone number.",
        "coverage_intent": "Exercise user-facing API success behavior, not raw API response shape.",
        "source_refs": [source_ref()],
        "metadata": {
            "chatbot_obligation": True,
            "planning_rule": "status_response_api_success",
            "required_entity": "phoneNumber",
        },
    }
    data.update(overrides)
    return data


def obligation_ledger_data(**overrides: object) -> dict:
    obligations = [
        obligation_data(),
        obligation_data(
            obligation_id="obl_api_schema",
            requirement_id="req_api_schema",
            obligation_type="non_chatbot_api_schema",
            status="skipped_by_policy",
            blocked_reason="API-schema-only requirement is not a chatbot test obligation by default.",
            description="Do not send this API schema detail to chatbot test generation.",
            coverage_intent="Keep raw API response-shape coverage out of chatbot test drafting.",
            source_refs=[source_ref("chunk_api_schema")],
            metadata={"chatbot_obligation": False, "planning_rule": "api_schema_only_requirement"},
        ),
        obligation_data(
            obligation_id="obl_agent",
            requirement_id="req_agent",
            obligation_type="human_handoff",
            description="Verify the bot sends the user to an agent when phone lookup cannot proceed.",
            coverage_intent="Exercise documented agent handoff, not self-service order-ID tracking.",
            source_refs=[source_ref("chunk_agent")],
            metadata={"chatbot_obligation": True, "planning_rule": "human_handoff"},
        ),
    ]
    data = {
        "obligation_ledger_id": "obl_ledger_001",
        "project_id": "demo_chatbot",
        "governed_ledger_id": "gov_ledger_001",
        "obligations": obligations,
    }
    data.update(overrides)
    return data


def conversation_turn(**overrides: object) -> dict:
    data = {"turn_id": "turn_001", "speaker": "user", "text": "Track my order."}
    data.update(overrides)
    return data


def assertion(**overrides: object) -> dict:
    data = {
        "assertion_id": "assert_001",
        "assertion_type": "bot_response_behavior",
        "target": "bot.final_response",
        "expected": "The bot provides the delivery status for the latest active order for phone 5551234567.",
    }
    data.update(overrides)
    return data


def valid_phone_turns() -> list[dict]:
    return [
        conversation_turn(
            turn_id="turn_001",
            speaker="system",
            text="Setup: API stub has registered phone 5551234567 and returns 200 OK with SHIPPED status.",
        ),
        conversation_turn(turn_id="turn_002", speaker="user", text="Track my order."),
        conversation_turn(
            turn_id="turn_003",
            speaker="bot",
            text="Please enter the 10-digit phone number used during checkout.",
        ),
        conversation_turn(turn_id="turn_004", speaker="user", text="5551234567"),
        conversation_turn(
            turn_id="turn_005",
            speaker="bot",
            text="Your latest active order is currently shipped and on its way.",
        ),
    ]


def draft_test_case_data(**overrides: object) -> dict:
    data = {
        "test_case_id": "tc_001",
        "title": "Track order by checkout phone",
        "status": "draft",
        "requirement_ids": ["req_phone"],
        "obligation_ids": ["obl_phone_success"],
        "source_refs": [source_ref()],
        "turns": valid_phone_turns(),
        "assertions": [assertion()],
    }
    data.update(overrides)
    return data


def draft_suite_data(test_cases: list[dict] | None = None, **overrides: object) -> dict:
    data = {
        "draft_suite_id": "draft_suite_001",
        "project_id": "demo_chatbot",
        "obligation_ledger_id": "obl_ledger_001",
        "test_cases": test_cases or [draft_test_case_data()],
    }
    data.update(overrides)
    return data


def validate_single(test_case: dict, source_package: dict | None = None) -> dict:
    result = validate_draft_suite(
        draft_suite_data(test_cases=[test_case]),
        governed_ledger_data(),
        obligation_ledger_data(),
        source_package if source_package is not None else source_package_data(),
    )
    return result.validated_suite.to_dict()["test_cases"][0]


def assert_non_exportable(test_case: dict, reason_fragment: str) -> None:
    assert test_case["status"] in {"needs_review", "rejected"}
    assert test_case["export_eligible"] is False
    assert any(reason_fragment in reason for reason in test_case["rejection_reasons"])


def test_raw_json_bot_output_is_non_exportable():
    test_case = draft_test_case_data(
        turns=[
            conversation_turn(turn_id="turn_001", speaker="user", text="Track my order using 5551234567."),
            conversation_turn(
                turn_id="turn_002",
                speaker="bot",
                text='{"success": true, "data": {"carrier": "UPS", "status": "SHIPPED"}}',
            ),
        ]
    )

    assert_non_exportable(validate_single(test_case), "raw API JSON bot turn")


def test_api_schema_fields_as_bot_dialogue_are_non_exportable():
    test_case = draft_test_case_data(
        turns=[
            conversation_turn(turn_id="turn_001", speaker="user", text="Track my order using 5551234567."),
            conversation_turn(
                turn_id="turn_002",
                speaker="bot",
                text=(
                    "success, data, carrier, status, trackingLink, expectedDeliveryDate, "
                    "orderId, type, maxLength, required, and nullability are returned."
                ),
            ),
        ]
    )

    assert_non_exportable(validate_single(test_case), "API schema details in bot dialogue")


def test_api_field_names_are_allowed_when_user_facing_source_supports_them():
    ref = source_ref("chunk_status_labels", "doc_status")
    governed = governed_ledger_data(
        requirements=[
            governed_requirement(
                requirement_id="req_status_labels",
                statement=(
                    "The chatbot shows user-facing status labels named success, data, carrier, "
                    "and status on the status screen."
                ),
                requirement_type="status_labels",
                source_refs=[ref],
                candidate_ids=["cand_status_labels"],
            )
        ],
        governance_summary={"validated": 1},
    )
    obligations = obligation_ledger_data(
        obligations=[
            obligation_data(
                obligation_id="obl_status_labels",
                requirement_id="req_status_labels",
                obligation_type="positive",
                description="Verify the bot presents the documented user-facing status labels.",
                coverage_intent="Exercise visible chatbot copy, not backend response schema.",
                source_refs=[ref],
                metadata={},
            )
        ]
    )
    source = source_package_data(
        document_ids=["doc_status"],
        chunks=[
            source_chunk(
                chunk_id="chunk_status_labels",
                document_id="doc_status",
                text=(
                    "The chatbot status screen shows user-facing labels named success, data, "
                    "carrier, and status. These labels are visible copy for customers."
                ),
                checksum="sha256:chunk-status-labels",
            )
        ],
    )
    test_case = draft_test_case_data(
        test_case_id="tc_status_labels",
        title="User-facing status labels",
        requirement_ids=["req_status_labels"],
        obligation_ids=["obl_status_labels"],
        source_refs=[ref],
        turns=[
            conversation_turn(turn_id="turn_001", speaker="user", text="Show my status summary."),
            conversation_turn(
                turn_id="turn_002",
                speaker="bot",
                text="Your status screen includes the success, data, carrier, and status labels.",
            ),
        ],
        assertions=[assertion(expected="The bot shows the user-facing status labels from the source.")],
    )

    result = validate_draft_suite(draft_suite_data(test_cases=[test_case]), governed, obligations, source)
    validated = result.validated_suite.to_dict()["test_cases"][0]

    assert validated["status"] == "valid"
    assert validated["export_eligible"] is True


def test_unsupported_order_id_self_service_flow_is_non_exportable():
    test_case = draft_test_case_data(
        turns=[
            conversation_turn(turn_id="turn_001", speaker="user", text="Track my order."),
            conversation_turn(turn_id="turn_002", speaker="bot", text="Please provide your Order ID."),
            conversation_turn(turn_id="turn_003", speaker="user", text="ORD-1001"),
            conversation_turn(turn_id="turn_004", speaker="bot", text="I found your order and it is shipped."),
        ],
    )

    assert_non_exportable(validate_single(test_case), "unsupported entity collection")


def test_unsupported_entity_collection_uses_generic_metadata_grounding():
    ref = source_ref("chunk_billing", "doc_billing")
    governed = governed_ledger_data(
        requirements=[
            governed_requirement(
                requirement_id="req_billing_lookup",
                statement="For billing help, the bot may collect the user's email address before showing invoice status.",
                requirement_type="billing_status",
                source_refs=[ref],
                candidate_ids=["cand_billing"],
            )
        ],
        governance_summary={"validated": 1},
    )
    obligations = obligation_ledger_data(
        obligations=[
            obligation_data(
                obligation_id="obl_billing_lookup",
                requirement_id="req_billing_lookup",
                obligation_type="positive",
                description="Verify the billing lookup flow using the supported email address input.",
                coverage_intent="Exercise the documented customer-facing billing lookup flow.",
                source_refs=[ref],
                metadata={"supported_entities": ["email address"]},
            )
        ]
    )
    source = source_package_data(
        document_ids=["doc_billing"],
        chunks=[
            source_chunk(
                chunk_id="chunk_billing",
                document_id="doc_billing",
                text=(
                    "For billing help, the chatbot may ask for the user's email address. "
                    "Account ID lookup is available only to human agents."
                ),
                checksum="sha256:chunk-billing",
            )
        ],
    )
    test_case = draft_test_case_data(
        test_case_id="tc_billing_account_id",
        title="Unsupported billing account ID collection",
        requirement_ids=["req_billing_lookup"],
        obligation_ids=["obl_billing_lookup"],
        source_refs=[ref],
        turns=[
            conversation_turn(turn_id="turn_001", speaker="user", text="I need invoice status."),
            conversation_turn(turn_id="turn_002", speaker="bot", text="Please provide your account ID."),
            conversation_turn(turn_id="turn_003", speaker="user", text="ACCT-1001."),
            conversation_turn(turn_id="turn_004", speaker="bot", text="I found the invoice status."),
        ],
        assertions=[assertion(expected="The bot gives invoice status after collecting a supported identifier.")],
    )

    result = validate_draft_suite(draft_suite_data(test_cases=[test_case]), governed, obligations, source)

    assert_non_exportable(result.validated_suite.to_dict()["test_cases"][0], "unsupported entity collection")


def test_order_id_self_service_is_allowed_when_source_explicitly_supports_it():
    ref = source_ref("chunk_order_id", "doc_order_id")
    governed = governed_ledger_data(
        requirements=[
            governed_requirement(
                requirement_id="req_order_id_lookup",
                statement="The chatbot may ask for Order ID so the user can self-serve warranty claim status.",
                requirement_type="status_response",
                source_refs=[ref],
                candidate_ids=["cand_order_id"],
                metadata={"supported_entities": ["Order ID"]},
            )
        ],
        governance_summary={"validated": 1},
    )
    obligations = obligation_ledger_data(
        obligations=[
            obligation_data(
                obligation_id="obl_order_id_lookup",
                requirement_id="req_order_id_lookup",
                obligation_type="positive",
                description="Verify claim status lookup when the user provides Order ID.",
                coverage_intent="Exercise documented chatbot self-service by Order ID.",
                source_refs=[ref],
                metadata={"supported_entities": ["Order ID"], "required_entity": "Order ID"},
            )
        ]
    )
    source = source_package_data(
        document_ids=["doc_order_id"],
        chunks=[
            source_chunk(
                chunk_id="chunk_order_id",
                document_id="doc_order_id",
                text=(
                    "The chatbot may ask for Order ID and users can self-serve warranty claim "
                    "status by entering that Order ID."
                ),
                checksum="sha256:chunk-order-id",
            )
        ],
    )
    test_case = draft_test_case_data(
        test_case_id="tc_order_id_supported",
        title="Supported claim lookup by Order ID",
        requirement_ids=["req_order_id_lookup"],
        obligation_ids=["obl_order_id_lookup"],
        source_refs=[ref],
        turns=[
            conversation_turn(turn_id="turn_001", speaker="user", text="Check my warranty claim."),
            conversation_turn(turn_id="turn_002", speaker="bot", text="Please provide your Order ID."),
            conversation_turn(turn_id="turn_003", speaker="user", text="ORD-1001."),
            conversation_turn(turn_id="turn_004", speaker="bot", text="Your warranty claim is in review."),
        ],
        assertions=[assertion(expected="The bot returns warranty claim status after the user provides Order ID.")],
    )

    result = validate_draft_suite(draft_suite_data(test_cases=[test_case]), governed, obligations, source)
    validated = result.validated_suite.to_dict()["test_cases"][0]

    assert validated["status"] == "valid"
    assert validated["export_eligible"] is True


def test_agent_order_id_lookup_reference_remains_valid_when_source_supported():
    test_case = draft_test_case_data(
        test_case_id="tc_agent",
        title="Agent lookup when phone is unavailable",
        requirement_ids=["req_agent"],
        obligation_ids=["obl_agent"],
        source_refs=[source_ref("chunk_agent")],
        turns=[
            conversation_turn(turn_id="turn_001", speaker="user", text="I do not have the phone number for my order."),
            conversation_turn(
                turn_id="turn_002",
                speaker="bot",
                text="I will direct you to an agent. The agent can locate your order using your email address or Order ID.",
            ),
        ],
        assertions=[
            assertion(
                expected="The bot directs the user to an agent and says the agent can use email address or Order ID.",
                target="bot.final_response",
            )
        ],
    )

    validated = validate_single(test_case)

    assert validated["status"] == "valid"
    assert validated["export_eligible"] is True


def test_placeholder_unresolved_variable_is_non_exportable():
    test_case = draft_test_case_data(
        turns=[
            conversation_turn(turn_id="turn_001", speaker="system", text="Setup: registered phone is [PHONE]."),
            conversation_turn(turn_id="turn_002", speaker="user", text="Track my order using [PHONE]."),
            conversation_turn(
                turn_id="turn_003",
                speaker="bot",
                text="Your latest active order status is <most_recent_active_order_status>.",
            ),
        ],
        assertions=[
            assertion(expected="The bot provides <most_recent_active_order_status> for [PHONE].")
        ],
    )

    assert_non_exportable(validate_single(test_case), "unresolved executable placeholder")


def test_invalid_positive_phone_path_is_non_exportable():
    test_case = draft_test_case_data(
        turns=[
            conversation_turn(
                turn_id="turn_001",
                speaker="system",
                text="Setup: API stub has registered phone 98765 and returns 200 OK.",
            ),
            conversation_turn(turn_id="turn_002", speaker="user", text="Track my order using 98765."),
            conversation_turn(turn_id="turn_003", speaker="bot", text="Your order is shipped."),
        ],
    )

    assert_non_exportable(validate_single(test_case), "invalid required entity test data")


def test_phone_number_is_not_globally_forced_to_ten_digits_without_source_support():
    ref = source_ref("chunk_callback", "doc_callback")
    governed = governed_ledger_data(
        requirements=[
            governed_requirement(
                requirement_id="req_callback_phone",
                statement="The bot asks for a callback phone number before creating a support ticket.",
                requirement_type="input_parameter",
                source_refs=[ref],
                candidate_ids=["cand_callback"],
            )
        ],
        governance_summary={"validated": 1},
    )
    obligations = obligation_ledger_data(
        obligations=[
            obligation_data(
                obligation_id="obl_callback_phone",
                requirement_id="req_callback_phone",
                obligation_type="positive",
                description="Verify the bot collects the callback phone number.",
                coverage_intent="Exercise the documented callback setup flow.",
                source_refs=[ref],
                metadata={"required_entity": "phone number"},
            )
        ]
    )
    source = source_package_data(
        document_ids=["doc_callback"],
        chunks=[
            source_chunk(
                chunk_id="chunk_callback",
                document_id="doc_callback",
                text="The bot asks for a callback phone number before creating a support ticket.",
                checksum="sha256:chunk-callback",
            )
        ],
    )
    test_case = draft_test_case_data(
        test_case_id="tc_callback_phone",
        title="Callback phone collection",
        requirement_ids=["req_callback_phone"],
        obligation_ids=["obl_callback_phone"],
        source_refs=[ref],
        turns=[
            conversation_turn(turn_id="turn_001", speaker="user", text="Create a support ticket."),
            conversation_turn(turn_id="turn_002", speaker="bot", text="Please provide your callback phone number."),
            conversation_turn(turn_id="turn_003", speaker="user", text="+44 20 7946 0958."),
            conversation_turn(turn_id="turn_004", speaker="bot", text="I created the support ticket."),
        ],
        assertions=[assertion(expected="The bot creates the support ticket after collecting the callback phone number.")],
    )

    result = validate_draft_suite(draft_suite_data(test_cases=[test_case]), governed, obligations, source)
    validated = result.validated_suite.to_dict()["test_cases"][0]

    assert validated["status"] == "valid"
    assert validated["export_eligible"] is True


def test_descriptive_bot_turn_is_non_exportable():
    test_case = draft_test_case_data(
        turns=[
            conversation_turn(turn_id="turn_001", speaker="user", text="Track my order."),
            conversation_turn(turn_id="turn_002", speaker="bot", text="Bot asks for phone number."),
        ]
    )

    assert_non_exportable(validate_single(test_case), "descriptive bot turn")


def test_invented_exact_wording_is_non_exportable_when_absent_from_linked_source():
    test_case = draft_test_case_data(
        turns=[
            conversation_turn(turn_id="turn_001", speaker="user", text="Track my order using 5551234567."),
            conversation_turn(turn_id="turn_002", speaker="bot", text="Your package is flying through space."),
        ],
        assertions=[
            assertion(
                assertion_type="equals_text",
                target="turn_002.text",
                expected="Your package is flying through space.",
            )
        ],
    )

    assert_non_exportable(validate_single(test_case), "exact wording is not supported by linked source")


def test_weak_meta_assertion_is_non_exportable():
    test_case = draft_test_case_data(
        assertions=[
            assertion(
                assertion_type="traceability",
                target="test_case_links",
                expected="Traceability is maintained and the requirement is covered.",
            )
        ]
    )

    assert_non_exportable(validate_single(test_case), "weak or meta-level assertion")


def test_missing_api_setup_stub_data_is_non_exportable_for_api_obligation():
    test_case = draft_test_case_data(
        turns=[
            conversation_turn(turn_id="turn_001", speaker="user", text="Track my order using 5551234567."),
            conversation_turn(turn_id="turn_002", speaker="bot", text="Your latest active order is shipped."),
        ]
    )

    assert_non_exportable(validate_single(test_case), "missing API setup or stub data")


def test_c11_oracle_flags_are_translated_to_non_exportable_status():
    test_case = draft_test_case_data(metadata={"oracle_flags": ["unsupported", "needs_review"]})

    assert_non_exportable(validate_single(test_case), "oracle flagged test for review")


def test_valid_grounded_chatbot_test_remains_export_eligible():
    validated = validate_single(draft_test_case_data())

    assert validated["status"] == "valid"
    assert validated["export_eligible"] is True
    assert "rejection_reasons" not in validated


def test_near_duplicate_test_cases_are_not_both_export_eligible():
    first = draft_test_case_data(test_case_id="tc_001", title="Track order by phone")
    second = draft_test_case_data(
        test_case_id="tc_002",
        title="Track order using phone",
        turns=[
            conversation_turn(
                turn_id="turn_001",
                speaker="system",
                text="Setup: API stub has registered phone 5551234567 and returns 200 OK with SHIPPED status!",
            ),
            conversation_turn(turn_id="turn_002", speaker="user", text="Track my order"),
            conversation_turn(
                turn_id="turn_003",
                speaker="bot",
                text="Please enter the 10 digit phone number used during checkout.",
            ),
            conversation_turn(turn_id="turn_004", speaker="user", text="5551234567"),
            conversation_turn(
                turn_id="turn_005",
                speaker="bot",
                text="Your latest active order is currently shipped and on its way!",
            ),
        ],
    )

    result = validate_draft_suite(
        draft_suite_data(test_cases=[first, second]),
        governed_ledger_data(),
        obligation_ledger_data(),
        source_package_data(),
    )

    first_validated, second_validated = result.validated_suite.to_dict()["test_cases"]
    assert first_validated["export_eligible"] is True
    assert second_validated["status"] == "rejected"
    assert second_validated["export_eligible"] is False
    assert "near-duplicate test case content" in second_validated["rejection_reasons"]


def test_skipped_by_policy_obligations_are_skipped_not_uncovered():
    result = validate_draft_suite(
        draft_suite_data(test_cases=[]),
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_api_schema",
                    statement="The API response includes orderId, carrier, status, and trackingLink fields.",
                    requirement_type="response_contract",
                    source_refs=[source_ref("chunk_api_schema")],
                    candidate_ids=["cand_api_schema"],
                    metadata={"api_schema_only": True, "chatbot_testable": False},
                )
            ],
            governance_summary={"validated": 1},
        ),
        obligation_ledger_data(
            obligations=[
                obligation_data(
                    obligation_id="obl_api_schema",
                    requirement_id="req_api_schema",
                    obligation_type="non_chatbot_api_schema",
                    status="skipped_by_policy",
                    source_refs=[source_ref("chunk_api_schema")],
                    metadata={"chatbot_obligation": False},
                )
            ]
        ),
        source_package_data(chunks=[source_chunk(chunk_id="chunk_api_schema", checksum="sha256:chunk-api-schema")]),
    )

    report = result.coverage_report.to_dict()
    assert report["obligation_counts"]["skipped"] == 1
    assert report["obligation_counts"]["uncovered"] == 0
    assert report["requirement_counts"]["skipped"] == 1
    assert report["requirement_counts"]["uncovered"] == 0
    assert "uncovered_requirement_ids" not in report
    assert "uncovered_obligation_ids" not in report


def test_skipped_requirements_do_not_create_misleading_chatbot_source_uncovered_counts():
    report = build_coverage_report(
        {
            "validated_suite_id": "validated_suite_001",
            "project_id": "demo_chatbot",
            "draft_suite_id": "draft_suite_001",
            "test_cases": [],
            "validation_summary": {},
        },
        governed_ledger_data(
            requirements=[
                governed_requirement(
                    requirement_id="req_api_schema",
                    statement="The API response data object contains orderId.",
                    requirement_type="response_contract",
                    source_refs=[source_ref("chunk_api_schema")],
                    candidate_ids=["cand_api_schema"],
                    metadata={"api_schema_only": True, "chatbot_testable": False},
                )
            ],
            governance_summary={"validated": 1},
        ),
        obligation_ledger_data(
            obligations=[
                obligation_data(
                    obligation_id="obl_api_schema",
                    requirement_id="req_api_schema",
                    obligation_type="non_chatbot_api_schema",
                    status="skipped_by_policy",
                    source_refs=[source_ref("chunk_api_schema")],
                    metadata={"chatbot_obligation": False},
                )
            ]
        ),
        source_package_data(chunks=[source_chunk(chunk_id="chunk_api_schema", checksum="sha256:chunk-api-schema")]),
    ).to_dict()

    assert report["source_chunk_counts"]["skipped"] == 1
    assert report["source_chunk_counts"]["uncovered"] == 0


def test_order_tracking_golden_fixture_round_trips():
    golden_dir = Path(__file__).parent / "fixtures" / "golden" / "test_validation_coverage"
    result = validate_draft_suite(
        json.loads((golden_dir / "draft_test_suite.json").read_text(encoding="utf-8")),
        json.loads((golden_dir / "governed_requirement_ledger.json").read_text(encoding="utf-8")),
        json.loads((golden_dir / "test_obligation_ledger.json").read_text(encoding="utf-8")),
        json.loads((golden_dir / "source_package.json").read_text(encoding="utf-8")),
    )

    assert result.validated_suite.to_dict() == json.loads(
        (golden_dir / "validated_test_suite.json").read_text(encoding="utf-8")
    )
    assert result.coverage_report.to_dict() == json.loads(
        (golden_dir / "coverage_report.json").read_text(encoding="utf-8")
    )
