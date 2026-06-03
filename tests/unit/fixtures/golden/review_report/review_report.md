# Review Report

Project: demo_chatbot

## Artifact References

- Governed requirements: gov_ledger_001
- Test obligations: obl_ledger_001
- Validated suite: validated_suite_001
- Coverage report: coverage_001

## Requirement Status

| Status | Count |
|---|---:|
| conflicting | 0 |
| duplicate | 0 |
| inferred | 0 |
| needs_clarification | 0 |
| out_of_scope | 0 |
| rejected | 0 |
| validated | 2 |

## Obligation Status

| Status | Count |
|---|---:|
| planned | 1 |
| skipped_by_policy | 1 |

## Validation Summary

| Status | Count |
|---|---:|
| export_eligible | 1 |
| needs_review | 4 |
| rejected | 0 |
| valid | 1 |

## Coverage Summary

### Requirements

| Metric | Count |
|---|---:|
| covered | 1 |
| skipped | 1 |
| total | 2 |
| uncovered | 0 |

### Obligations

| Metric | Count |
|---|---:|
| blocked | 0 |
| covered | 1 |
| skipped | 1 |
| total | 2 |
| uncovered | 0 |

### Tests

| Metric | Count |
|---|---:|
| export_eligible | 1 |
| needs_review | 4 |
| rejected | 0 |
| total | 5 |
| valid | 1 |

### Source Chunks

| Metric | Count |
|---|---:|
| covered | 1 |
| skipped | 1 |
| total | 2 |
| uncovered | 0 |
| with_requirements | 2 |
| without_requirements | 0 |

## Coverage Gaps

- Uncovered requirements: none
- Uncovered obligations: none

## Conflicts

- None

## Approval Needed

- None

## Blocked Obligations

- None

## Rejected or Non-Exportable Tests

- tc_002 (needs_review, export_eligible=False): Unsupported order ID self-service tracking. Reasons: unsupported entity collection; invalid required entity test data; missing API setup or stub data
- tc_003 (needs_review, export_eligible=False): Raw API response shown as chatbot output. Reasons: raw API JSON bot turn
- tc_004 (needs_review, export_eligible=False): Placeholder order status response. Reasons: unresolved executable placeholder; invalid required entity test data
- tc_005 (needs_review, export_eligible=False): Traceability-only order tracking assertion. Reasons: weak or meta-level assertion
