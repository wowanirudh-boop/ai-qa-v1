# Domain Leakage Audit

Date: 2026-06-04

## Verdict

DOMAIN_LEAKAGE_FOUND

## Summary

- Files inspected: required architecture docs, C07-C15 component specs, every Python product file under `src/ai_testgen/*.py`, every runtime skill JSON under `skills/*.json`, and representative tests, golden fixtures, docs, examples, and acceptance data.
- Product/runtime files inspected: `artifact_store.py`, `cli.py`, `codex_cli_adapter.py`, `coverage.py`, `document_ingestion.py`, `executor_export.py`, `obligation_planning.py`, `orchestrator.py`, `project_config.py`, `requirement_atomization.py`, `requirement_extraction.py`, `requirement_governance.py`, `review_report.py`, `schemas.py`, `skill_runtime.py`, `skill_runtime_config.py`, `source_ledger.py`, `test_generation.py`, `test_validation.py`, `validators.py`, `__init__.py`, plus all four skill JSON files.
- Overall finding: confirmed domain leakage exists in C10 product code. C11 skill prompts contain non-blocking but overfit order/phone wording. C12 appears generic and source/metadata-driven after review.
- Tests were not run. This was a static audit only.

## Scan Commands Run

- `rg --files src/ai_testgen`
- `rg --files skills`
- `rg --files tests`
- `rg --files examples`
- `rg --files docs`
- `if (Test-Path test_data) { rg --files test_data }`
- `rg -n -i --glob '!**/__pycache__/**' "order|order_id|orderId|order number|tracking|track order|order tracking|shipment|carrier|trackingLink|tracking_link|expectedDeliveryDate|expected_delivery_date|delivery|shipped" src/ai_testgen skills tests examples docs test_data`
- `rg -n -i --glob '!**/__pycache__/**' "phone|phone_number|10 digit|10-digit|ten digit|\\d\{10\}|E\.164|mobile" src/ai_testgen skills tests examples docs test_data`
- `rg -n -i --glob '!**/__pycache__/**' "success|data|status|type|maxLength|required|nullable|nullability|schema|payload|raw JSON|json" src/ai_testgen skills tests examples docs test_data`
- `rg -n -i --glob '!**/__pycache__/**' "unsupported_order|order_tracking|tracking_flow|positive_phone|invalid_phone|api_schema_fields|raw_json_bot|descriptive_bot|weak_assertion|placeholder|missing_stub|missing_setup|near_duplicate" src/ai_testgen skills tests examples docs test_data`
- `rg -n -i --glob '!**/__pycache__/**' "order_tracking|acceptance|golden/test_validation_coverage|test_data/acceptance" src/ai_testgen skills tests examples docs test_data`
- `rg -n -i --glob '!**/__pycache__/**' "local_fake|openai|anthropic|llm|provider|codex_cli|SkillRuntime|run_skill|execute" src/ai_testgen skills`
- Static AST/string-literal scan via `uv run python -` after direct `python` was unavailable and sandboxed `uv` cache access failed.

## Findings Table

| ID | Classification | File | Line/function | Component | Evidence | Why it is or is not domain leakage | Recommended action | Counterexample tests needed |
|---|---|---|---|---|---|---|---|---|
| DL-001 | BLOCKER | `src/ai_testgen/obligation_planning.py` | `_mentions_api_response_schema`, lines 568-592 | C10 | The generic API-schema detector includes `order details data`, `orderid field`, `carrier value`, `trackinglink value`, and `expecteddeliverydate value`. | This changes generic obligation planning based on order-tracking API field names. A generic C10 should classify API schema details from requirement type, metadata, and source/user-facing semantics, not from one fixture's response fields. | Replace fixture-field cues with generic contract/metadata-driven classification. Keep `api_schema_only`, `chatbot_testable`, requirement type, and source/user-facing cues as the decision inputs. | Yes |
| DL-002 | BLOCKER | `src/ai_testgen/obligation_planning.py` | `_is_missing_entity_requirement`, `_is_provided_entity_requirement`, lines 669-704 | C10 | Missing/provided entity detection is hardcoded around `phone`, `phonenumber`, `order number`, `order id`, `order status`, `registered phone number`, `track`, `delivery status`, and `latest order`. | This makes generic obligation existence depend on order-tracking/phone language. It can create chatbot obligations for those entities while missing equivalent non-order entities such as account ID, email, claim number, appointment date, or policy number. | Drive entity obligations from `requirement_type`, `required_entity`, `supported_entities`, source-backed collection wording, and validation metadata. Avoid hardcoded order/phone lists. | Yes |
| DL-003 | BLOCKER | `src/ai_testgen/obligation_planning.py` | `_mentions_api_error_condition`, `_is_faq_like_requirement`, lines 607-618 and 721-730 | C10 | API error/FAQ detection includes `no active orders` and `email address or order id`. | These are fixture-specific phrases embedded in generic C10 planning. They can promote order-tracking branches while equivalent non-order branches are ignored unless they match other generic cues. | Replace with generic documented error and FAQ/handoff cues derived from requirement type/metadata/source text. | Yes |
| DL-004 | WARNING | `tests/unit/test_obligation_planning.py` | lines 307-440, 447-504 | C10 tests | Unit tests assert C10 behavior using order-tracking response fields, 10-digit phone collection, track-order prompts, no-active-orders errors, and order-tracking API errors. | Domain language in tests is allowed, but these tests encode the leaked behavior in DL-001 through DL-003. They will preserve the product leak until rewritten or supplemented. | When fixing C10, replace or supplement these with non-order counterexamples and metadata-driven assertions. | Yes |
| DL-005 | WARNING | `skills/test_case_writer_v1.json` | lines 31-36 and prompt text line 8 | C11 skill | Runtime prompt says order-tracking self-service tracking must use `phoneNumber`; says not to use order ID/order number unless linked source documents it; names order/phone placeholders such as `<registered_checkout_phone_number>`, `<most_recent_active_order_status>`, `{orderId}`, and `{formattedDate}`. | The source-support exception mitigates this, but the wording is not example-scoped and can bias C11 globally toward a single order-tracking fixture. Runtime skills are product assets, so overfit prompt wording matters. | Rewrite as generic unsupported-entity/test-data guidance. If order tracking is kept as an example, label it clearly as an example and make the rule source/metadata-driven. | Yes |
| DL-006 | WARNING | `skills/oracle_generator_v1.json` | line 27 and prompt text line 8 | C11 skill | Oracle prompt says to flag `unsupported order-ID flow`. | This is an overfit phrase in a runtime skill. It does not by itself ban order ID globally, but the generic concept should be unsupported entity collection or unsupported journey. | Reword to generic unsupported entity/journey validation, optionally with order ID as an example only. | Yes |
| DL-007 | OK | `src/ai_testgen/test_validation.py` | lines 501-548, 578-621, 651-719, 729-960, 1290-1295 | C12 | Validators check raw JSON bot turns, API-schema dialogue, descriptive bot turns, unsupported entity collection, placeholders, entity data, API setup, exact wording, weak assertions, and duplicates. `10-digit` is only normalized to `10 digit`; digit lengths are parsed from linked format text. | Reviewed behavior is generic and source/metadata-driven. Required entities come from metadata/source support, and digit length is inferred from linked format text rather than hardcoded as 10 digits. | No required fix. Keep C12 counterexamples. | No new C12 blocker tests; keep existing coverage. |
| DL-008 | OK | `tests/unit/test_test_validation_coverage.py` | lines 289-355, 431-492, 559-616 | C12 tests | Tests allow API field names when source says they are user-facing labels, allow Order ID self-service when source/metadata supports it, and allow non-10-digit/E.164-like callback phone when source does not require 10 digits. | These tests are valid counterexamples proving C12 is not globally banning order/API fields or globally forcing 10-digit phone data. | Preserve these tests. Add analogous C10 tests. | C10 only |
| DL-009 | OK | `src/ai_testgen/requirement_extraction.py`, `src/ai_testgen/requirement_atomization.py`, `src/ai_testgen/test_generation.py` | C07 lines 101-164, C08 lines 151-161 and 229-300, C11 lines 120-242 | C07/C08/C11 code | Skill-required components load skill definitions, create bounded artifacts, and invoke `runtime.run_skill`. | No direct LLM/provider calls in these business components. C11 adds linked requirements/source chunks to bounded metadata, but it does not generate tests from raw documents directly. | No domain-leakage fix. | No |
| DL-010 | OK | `src/ai_testgen/review_report.py`, `src/ai_testgen/executor_export.py`, `src/ai_testgen/orchestrator.py` | C13 lines 117-192, C14 lines 179-216, C15 lines 108-235 and 729-747 | C13/C14/C15 | C13 reports upstream statuses/reasons, C14 filters by exportability and link checks, C15 calls components and validates artifacts. | No order-tracking behavior, no semantic revalidation in C13, no domain-specific export filters in C14, and no fixture-specific orchestration in C15. | No fix. | No |
| DL-011 | OK | `src/ai_testgen/**/*.py`, `skills/**/*.json` | mechanical scan | All runtime/product assets | `rg` found no product/runtime hits for `test_data`, `acceptance`, `order_tracking`, or `golden` paths. | No production code or runtime skill appears to reference acceptance fixture paths or names to determine behavior. | No fix. | No |
| DL-012 | OK | `docs/**`, `test_data/acceptance/order_tracking/**`, `tests/unit/fixtures/**` | e.g. `docs/acceptance/order_tracking_semantic_quality_rca.md`, `test_data/acceptance/order_tracking/source_docs/*` | Docs/fixtures | Order-tracking language appears in status docs, an RCA, golden fixtures, acceptance source docs, and test examples. | This is allowed by audit rules when it is documentation, examples, or fixture data and does not drive runtime behavior. | No product fix. | No |

## Component Notes

### C07

Clean. `requirement_extraction.py` invokes SkillRuntime with bounded source packages and validates candidate/source links. No order/phone/API-schema fixture-specific suppression or promotion was found in product code or `skills/requirement_extraction_v1.json`.

### C08

Clean for domain leakage. `requirement_atomization.py` production path uses SkillRuntime. The deterministic helper is explicitly named `atomize_candidate_package_deterministic_for_tests` and is generic. `skills/requirement_atomization_v1.json` contains no order/phone terms.

### C09

Clean for domain leakage. Governance applies generic status, duplicate, conflict, and approval behavior. No hardcoded order/phone/API-schema business rules were found.

### C10

Confirmed leakage. Generic obligation planning contains hardcoded order-tracking and phone-number terms that affect API-schema classification, entity obligation planning, API error planning, and FAQ-like planning.

### C11

Code path is clean: test generation uses SkillRuntime and bounded obligations. Runtime skill wording is overfit: `test_case_writer_v1.json` and `oracle_generator_v1.json` contain order/phone-specific rules that should be converted to generic unsupported-entity/source-grounding language.

### C12

Clean for confirmed domain leakage. Semantic hygiene validators are generic and source/metadata-driven. Existing tests include counterexamples for API field names, Order ID support, and non-10-digit phone formats.

### C13

Clean. Reporting surfaces upstream counts, gaps, blocked obligations, conflicts, approval needs, and non-exportable test reasons without domain-specific suppression or revalidation.

### C14

Clean. Export filters by `test_case.is_exportable`, source refs, requirement status, obligation status, link consistency, and export package validation. No domain-specific export filtering was found.

### C15

Clean. Orchestrator calls component runners, validates artifact paths and schemas, and performs lightweight cross-artifact link validation. No order-tracking acceptance behavior was found.

### Skills

`requirement_extraction_v1.json` and `requirement_atomization_v1.json` are generic. `test_case_writer_v1.json` and `oracle_generator_v1.json` contain overfit order/phone wording; classify as warnings because some source-support exceptions exist, but the wording is still product-runtime text.

### Schemas

Clean. Schema enums and contract validators are generic. No domain-specific schema fields, bans, or fixture path logic were found.

### Tests/Fixtures

Domain language in acceptance fixtures, golden fixtures, examples, and documentation is allowed. C12 has good counterexample tests. C10 tests currently assert the leaked behavior and should be changed when C10 is fixed.

## Counterexample Tests Recommended

- C10: entity collection for a non-order domain, such as appointment booking, creates missing/provided obligations using `required_entity` or source-backed collection text.
- C10: invalid entity obligation is created for non-phone validation, such as email format, claim number format, or account ID format, when source/metadata defines validation rules.
- C10: Order ID self-service is allowed when linked source/metadata explicitly supports chatbot self-service by Order ID.
- C10: phone number is not privileged or forced to 10 digits; E.164 or another source/config-supported format should plan and validate correctly.
- C10: API field names like `status` are not skipped as API-schema-only when source says the bot exposes them as user-facing labels.
- C10: non-order API errors such as appointment not found, payment declined, or claim not found produce `api_error` only when source documents user-facing bot behavior.
- C11 skill-definition tests: runtime prompts should not contain global order-tracking phoneNumber or order-ID bans; any domain terms should be clearly example-scoped.
- Keep C12 tests proving raw JSON, placeholders, weak/meta assertions, missing setup, descriptive bot turns, exact wording, and duplicates are blocked generically.

## Required Fixes

Required only for BLOCKER findings:

- Fix C10 `obligation_planning.py` so obligation existence and skip/block decisions are generic, metadata/source-driven, and not tied to order-tracking/phone terms.
- Update C10 tests so they no longer assert fixture-specific planning behavior as generic product policy.

## Warnings

- C11 writer skill prompt is overfit to order tracking and phoneNumber.
- C11 oracle skill prompt uses `unsupported order-ID flow` instead of a generic unsupported entity/journey concept.
- C10 tests currently preserve the C10 leak and will need counterexample coverage during the fix.

## Assumptions

- The current repo is source of truth.
- Domain language in docs, acceptance data, golden fixtures, and unit-test examples is allowed unless it encodes or drives generic runtime behavior.
- Static review is sufficient for this audit; no tests were required to confirm the repo is green.
- `codex_cli_adapter.py` is inside the C06 SkillRuntime boundary, so its subprocess use is not a business-component provider call.

## Non-goals Honored

- No live `codex_cli` run.
- No SkillRuntime live calls.
- No LLM/provider SDK/API calls.
- No product code refactor.
- No skill edits.
- No schema edits.
- No test edits.
- No architecture broadening.
