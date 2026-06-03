import json
from pathlib import Path

from ai_testgen.skill_runtime import load_skill_definition


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_requirement_extraction_skill_definition_loads_with_c07_contracts():
    definition = load_skill_definition(REPO_ROOT / "skills" / "requirement_extraction_v1.json")

    assert definition.skill_id == "requirement_extraction_v1"
    assert definition.input_contract == "SourcePackage"
    assert definition.output_contract == "CandidateRequirementPackage"


def test_requirement_extraction_skill_definition_includes_required_rules():
    definition = load_skill_definition(REPO_ROOT / "skills" / "requirement_extraction_v1.json")
    definition_text = json.dumps(definition.to_dict(), sort_keys=True)

    required_phrases = [
        "extract candidate chatbot testing requirements from bounded source chunks",
        "Return JSON only",
        "Use only the provided bounded SourcePackage",
        "Do not infer unsupported bot behavior",
        "Do not create atomic requirements",
        "Do not generate test cases",
        "Every candidate requirement must include non-empty source_refs",
        "Every source_ref must point to a chunk in the input SourcePackage",
        "Candidate confidence must be between 0 and 1",
        "Mark or report chunks that contain no testable requirements",
        "ambiguous chunks as unclear",
        "out-of-scope chunks as out_of_scope",
        "Preserve exact document_id and chunk_id values from input",
    ]

    for phrase in required_phrases:
        assert phrase in definition_text


def test_requirement_atomization_skill_definition_loads_with_c08_contracts():
    definition = load_skill_definition(REPO_ROOT / "skills" / "requirement_atomization_v1.json")

    assert definition.skill_id == "requirement_atomization_v1"
    assert definition.input_contract == "CandidateRequirementPackage"
    assert definition.output_contract == "AtomicRequirementLedger"


def test_requirement_atomization_skill_definition_includes_required_rules():
    definition = load_skill_definition(REPO_ROOT / "skills" / "requirement_atomization_v1.json")
    definition_text = json.dumps(definition.to_dict(), sort_keys=True)

    required_phrases = [
        "split candidate requirements into atomic source-backed requirements",
        "Return JSON only",
        "Do not generate tests",
        "Do not govern requirements",
        "Do not deduplicate final requirements",
        "Do not create obligations",
        "Do not infer unsupported behavior",
        "Preserve candidate_ids",
        "Preserve source_refs",
        "If a candidate is already atomic, return one atomic requirement",
        "If a candidate is broad, split it into one-behavior, one-trigger, one-outcome requirements",
        "Mark source-derived requirements as atomic_draft",
        "Use origin source_derived",
        "Do not create source-derived requirements without source_refs",
        "preserves uncertainty rather than inventing behavior",
    ]

    for phrase in required_phrases:
        assert phrase in definition_text


def test_test_case_writer_skill_definition_loads_with_c11_contracts():
    definition = load_skill_definition(REPO_ROOT / "skills" / "test_case_writer_v1.json")

    assert definition.skill_id == "test_case_writer_v1"
    assert definition.input_contract == "TestObligationLedger"
    assert definition.output_contract == "DraftTestSuite"


def test_test_case_writer_skill_definition_includes_required_rules():
    definition = load_skill_definition(REPO_ROOT / "skills" / "test_case_writer_v1.json")
    definition_text = json.dumps(definition.to_dict(), sort_keys=True)

    required_phrases = [
        "draft chatbot test cases from bounded test obligations",
        "Return JSON only",
        "Read only the provided bounded TestObligationLedger",
        "Treat generated tests as chatbot conversation tests, not API-contract tests",
        "Use obligation.description, obligation.coverage_intent, and obligation.metadata as primary generation guidance when present",
        "Preserve requirement_ids, obligation_ids, and source_refs exactly from the input",
        "Do not read raw source documents",
        "Do not create requirements",
        "Do not create obligations",
        "Do not validate coverage",
        "Do not decide export eligibility",
        "Every test case must have non-empty requirement_ids",
        "Every test case must have non-empty obligation_ids",
        "Every obligation_id must come from the input TestObligationLedger",
        "Preserve source_refs from linked obligations",
        "Bot turns must be actual chatbot utterances, not descriptions",
        "Do not output raw API JSON as bot text unless the source explicitly says the chatbot displays raw JSON",
        "Do not invent unsupported user journeys",
        "self-service tracking must use phoneNumber",
        "do not use order ID/order number for self-service tracking",
        "Do not use placeholders or unresolved variables in executable fields",
        "<registered_checkout_phone_number>",
        "GLOBAL_INTENT_UTTERANCE",
        "{formattedDate}",
        "Positive phone-number paths must use valid source/config-supported phone data",
        "If no concrete valid phone/API fixture exists, do not fabricate data",
        "Use exact documented bot wording when the source provides exact wording",
        "Do not invent exact wording when the source only describes behavior",
        "Include clear preconditions/setup when API state, API stubbing, customer/order data, or human handoff state is required",
        "If the obligation lacks enough information for an executable test, do not fabricate missing data",
    ]

    for phrase in required_phrases:
        assert phrase in definition_text


def test_oracle_generator_skill_definition_loads_with_c11_contracts():
    definition = load_skill_definition(REPO_ROOT / "skills" / "oracle_generator_v1.json")

    assert definition.skill_id == "oracle_generator_v1"
    assert definition.input_contract == "DraftTestSuite"
    assert definition.output_contract == "DraftTestSuite"


def test_oracle_generator_skill_definition_includes_required_rules():
    definition = load_skill_definition(REPO_ROOT / "skills" / "oracle_generator_v1.json")
    definition_text = json.dumps(definition.to_dict(), sort_keys=True)

    required_phrases = [
        "draft expected outcomes and assertions",
        "Return JSON only",
        "Read only the provided DraftTestSuite",
        "Do not read raw source documents",
        "Do not create requirements",
        "Do not create obligations",
        "Do not validate coverage",
        "Do not decide export eligibility",
        "Preserve test_case_id, requirement_ids, obligation_ids, source_refs, title, status, and conversation turns",
        "Assertions must be specific enough for a validator or reviewer to evaluate",
        "Assertions must evaluate observable chatbot behavior, not traceability metadata alone",
        "Assertions must not pass merely by checking requirement_ids, obligation_ids, or source_refs",
        "Assertions must include concrete pass/fail criteria",
        "Assertions must identify required facts and prohibited unsupported claims",
        "Assertions must not bless unsupported draft turns",
        "Assertions must not require exact wording unless the source requires exact wording",
        "If a draft test contains placeholders, raw JSON bot output, unsupported order-ID flow, or descriptive bot turns, flag the issue",
        "Ground assertions in linked requirement, obligation, source refs, source text, and obligation metadata where available",
        "Distinguish bot-visible behavior, API setup/stub behavior, executor preconditions, and internal traceability metadata",
    ]

    for phrase in required_phrases:
        assert phrase in definition_text
