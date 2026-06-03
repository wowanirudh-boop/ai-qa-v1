# Order Tracking Semantic Quality RCA

Run context:

- project_id: `order_tracking_acceptance`
- run_id: `order_tracking_live_20260602_215838`
- artifact_root: `artifacts/order_tracking_acceptance/order_tracking_live_20260602_215838`

## Executive Verdict

Pipeline architecture passed. Live `codex_cli` execution passed with warnings. Semantic test quality failed.

The acceptance run generated and exported 162 tests, but only 15 were classified as `KEEP`, 41 as `KEEP_WITH_MINOR_EDIT`, 26 as `NEEDS_REVIEW`, and 80 as `REJECT`. The main failure was that structurally valid tests were not semantically trustworthy: traceability links were present, but many exported tests invented behavior, duplicated weak scenarios, used unsupported test data, or were not executable by a downstream chatbot executor.

## Original Quality Counts

| Classification | Count |
|---|---:|
| KEEP | 15 |
| KEEP_WITH_MINOR_EDIT | 41 |
| NEEDS_REVIEW | 26 |
| REJECT | 80 |
| Total generated/exported | 162 |

## Root-Cause Summary

Primary cause: combined C10/C11/C12 failure.

- C10 over-generated bare `positive` and `negative` obligations for every validated requirement.
- C11 filled underspecified obligations with invented dialogue.
- C12 enforced structural traceability but not semantic executability.
- C08 and C09 contributed by allowing API-schema details to become governed chatbot-testable requirements.
- C07 was not the primary defect.

## Root-Cause Counts

| Primary root cause | Count |
|---|---:|
| C11_TEST_WRITER_HALLUCINATION | 40 |
| C10_OBLIGATION_OVERGENERATION | 34 |
| C08_ATOMIZATION_OVERREACH | 12 |
| C12_VALIDATION_GAP | 8 |
| FIXTURE_TEST_DATA_GAP | 5 |
| SOURCE_AMBIGUITY | 4 |
| C11_ORACLE_WEAKNESS | 2 |
| C09_GOVERNANCE_MISSING_FILTER | 1 |
| C07_EXTRACTION_OVERREACH | 0 |

## Issue-Type Counts

Issue counts overlap because a single bad test can have more than one issue.

| Issue type | Count |
|---|---:|
| missing_executor_setup | 38 |
| non_user_facing_api_behavior | 33 |
| vague_or_meta_assertion | 31 |
| duplicate_or_redundant | 31 |
| unclear_pass_fail_criteria | 29 |
| weakly_supported | 26 |
| api_schema_as_chatbot_dialogue | 26 |
| invented_exact_bot_wording | 22 |
| unsupported_order_id_flow | 21 |
| placeholder_or_unresolved_variable | 12 |
| source_contradiction | 10 |
| invalid_phone_positive_path | 7 |

## Component-Level Diagnosis

### C07 Requirement Extraction

C07 was not the primary defect. Candidate requirements were generally source-backed and traceable. The main gap is that extracted candidates did not carry enough downstream execution-domain metadata to distinguish chatbot-executable behavior from API-contract details.

Recommended action: do not treat C07 as the first remediation target. Consider adding optional candidate metadata later for executor domain, such as `chatbot_behavior`, `api_contract`, `faq_content`, or `non_testable_context`.

### C08 Requirement Atomization

C08 contributed by atomizing API response schema details into requirements that later became chatbot-testable. Examples include requirements about `success`, `data`, `orderId`, `carrier`, `trackingLink`, and `expectedDeliveryDate` as API fields.

Recommended action: preserve API-contract details as requirements only if they can be routed to an API-contract test track, or mark them as unsuitable for chatbot test generation.

### C09 Requirement Governance

C09 validated all 81 source-derived requirements and did not mark API-schema-only requirements, duplicates, overbroad requirements, or executor-unclear requirements as blocked, out-of-scope, or needing review.

Recommended action: add governance checks or metadata-driven status decisions for requirements that are traceable but not chatbot-executable.

### C10 Obligation Planning

C10 was a major failure point. Because the project config requested positive and negative tests, and most requirement types used the generic fallback path, every validated requirement received exactly one `positive` and one `negative` obligation. The obligations had no descriptions or coverage intent, leaving C11 to infer scenarios from polarity alone.

Recommended action: C10 should not generate chatbot obligations for API-schema-only requirements by default, and should not generate negative obligations unless the source supports a meaningful negative condition.

### C11 Test Case Writer and Oracle Generator

C11 was the largest direct source of bad tests. It invented unsupported order-ID self-service flows, raw API JSON bot outputs, placeholders, invalid phone-number positive paths, exact bot wording not present in source, descriptive bot turns, and meta-level assertions.

Recommended action: strengthen `test_case_writer_v1.json` and `oracle_generator_v1.json` so skill outputs must be executable, source-grounded, and observable. If the obligation is underspecified, the skill should produce a blocked or needs-review draft rather than inventing missing setup.

### C12 Validation and Coverage

C12 correctly enforced structural traceability, but it did not enforce semantic executability. It allowed tests with valid IDs/source refs to become `valid` and exportable even when they contained placeholders, invalid test data, non-user-facing API behavior, raw JSON bot turns, unsupported order-ID paths, or traceability-only assertions.

Recommended action: add semantic hygiene validators before export eligibility is granted.

### Fixture and Config

The fixture did not provide concrete executor-ready data for valid phones, invalid phones, API success payloads, API error payloads, no-active-order setup, or API stubbing capability. C11 filled those gaps with invented examples.

Recommended action: add explicit fixture/config data and executor capability declarations before the next live generation run.

## Highest-Leverage Fixes

1. C10: skip or block chatbot obligations for API-schema-only requirements and avoid automatic negative obligations unless source-supported.
2. C11: strengthen writer/oracle skill definitions against unsupported order-ID flow, raw API JSON bot output, placeholders, invalid positive phone data, invented exact wording, and meta assertions.
3. C12: add semantic hygiene validators for placeholders, descriptive bot turns, raw JSON bot utterances, traceability-only assertions, invalid order-tracking phone data, unsupported order-ID self-service inputs, and exact standardized message enforcement where source requires it.
4. Fixture/config: add concrete valid phones, invalid phones, API success payloads, API error payloads, no-active-order setup, and executor capability declarations.

## Proposed Next Implementation Order

1. C10 obligation planning hardening
2. C11 skill-definition hardening
3. C12 semantic validation hardening
4. Fixture/config data hardening
5. Fresh acceptance rerun and semantic review

## Remediation Plan

### Must Fix Before Next Live Generation Run

| Area | Fix | Expected benefit | Risk | Tests needed | Scope |
|---|---|---|---|---|---|
| C10 obligation planning | Add executor-domain-aware obligation decisions and skip/block API-schema-only requirements for chatbot export. | Prevents large classes of non-chatbot tests from reaching C11. | Coverage counts will drop and reports must explain skipped/blocked obligations. | Yes | Generic architecture |
| C10 obligation planning | Generate negative obligations only when source or metadata defines a meaningful negative case. | Reduces duplicate and invented negative tests. | Requires clearer obligation policy. | Yes | Generic architecture |
| C11 skill definitions | Forbid unsupported order-ID self-service flows, raw API JSON bot output, unresolved placeholders, invalid positive phone data, invented exact wording, and meta assertions. | Reduces hallucinated tests and executor-unready outputs. | Skill may produce fewer tests or mark more cases uncertain. | Yes, with golden skill-output fixtures | Generic architecture |
| C12 validation | Add semantic hygiene validation before export eligibility. | Prevents structurally valid but semantically bad tests from export. | Some validators may need project-specific configuration to avoid false positives. | Yes | Generic plus fixture-specific |
| Fixture/config | Add concrete test data and API stub assumptions. | Gives C11 enough data to draft executable tests. | Fixture maintenance burden. | Yes | Order-tracking-specific |

### Should Fix Before Demo

- Add API-contract vs chatbot-test classification to governed requirements or obligations.
- Add obligation `description` and `coverage_intent` so C11 receives precise scenario duties.
- Improve review report quality so semantic warnings are visible, not only structural counts.
- Add fuzzy duplicate detection in C12 or review reporting.

### Nice To Have

- Split exported chatbot tests from API-contract tests.
- Add source-chunk overgeneration checks.
- Add acceptance-quality thresholds as a separate semantic review gate.

## Target Acceptance Shape

A healthier order-tracking fixture should produce roughly 35-55 chatbot tests, not 162.

Expected chatbot behaviors to cover:

- Start flow `Talk to an agent`.
- Track-order prompt.
- Valid 10-digit phone number collection.
- API call setup for `GET /api/v1/orders/track?phoneNumber={input}`.
- Global intents while waiting for phone number: `Talk to an agent`, `Cancel`, and `No`.
- API success behavior for `PENDING`, `PROCESSING`, `SHIPPED`, `OUT_FOR_DELIVERY`, and `DELIVERED`.
- API error behavior for 400, 401, 404, 429, and 500 using documented standardized messages.
- Unhandled input fallback and human transfer.
- FAQ behavior for missing registered phone number and agent lookup by email address or Order ID.

API details that should be excluded from chatbot tests or moved to API-contract tests:

- Top-level `success` field.
- `data` object shape.
- Raw `orderId`, `carrier`, `trackingLink`, and `expectedDeliveryDate` field constraints.
- Type/max-length/nullability rules for API response fields.
- Raw API JSON as bot response text.

PASS criteria for the next semantic quality review:

- 85-90% of generated/exported tests are `KEEP` or `KEEP_WITH_MINOR_EDIT`.
- Zero raw API JSON bot utterances.
- Zero unsupported order-ID self-service paths.
- Zero unresolved placeholders.
- `REJECT` plus `NEEDS_REVIEW` under 10%.
- All exported tests have concrete setup and objective pass/fail criteria.

## Files Changed

- Added `docs/acceptance/order_tracking_semantic_quality_rca.md`.

## Commands Run

Read-only inspection:

- `Get-Content -Raw AGENTS.md`
- `Get-Content -Raw docs/CURRENT_STATUS.md`
- `Get-Content -Raw docs/ARCHITECTURE.md`
- `Get-Content -Raw docs/PIPELINE.md`
- `Get-Content -Raw docs/CODEX_WORKFLOW.md`
- `Test-Path docs/acceptance`

Filesystem setup for requested documentation artifact:

- `New-Item -ItemType Directory -Path docs/acceptance -Force`

No pipeline commands, runtime skills, `codex_cli`, provider SDK/API calls, or test commands were run.

## Assumptions

- This artifact records the completed RCA and does not reopen the semantic review.
- Creating the requested Markdown file and parent documentation directory is allowed.
- The current goal is documentation preservation only, not implementation.

## Non-Goals

- No runtime code changes.
- No test changes.
- No pipeline rerun.
- No skill execution.
- No `codex_cli` call.
- No provider SDK/API integration.
- No architecture redesign.
