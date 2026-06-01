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
| conflicting | 1 |
| duplicate | 0 |
| inferred | 0 |
| needs_clarification | 0 |
| out_of_scope | 0 |
| rejected | 0 |
| validated | 1 |

## Obligation Status

| Status | Count |
|---|---:|
| blocked_unclear_requirement | 1 |
| planned | 1 |

## Validation Summary

| Status | Count |
|---|---:|
| export_eligible | 1 |
| needs_review | 1 |
| rejected | 1 |
| valid | 1 |

## Coverage Summary

### Requirements

| Metric | Count |
|---|---:|
| covered | 1 |
| total | 2 |
| uncovered | 1 |

### Obligations

| Metric | Count |
|---|---:|
| blocked | 1 |
| covered | 1 |
| skipped | 0 |
| total | 2 |
| uncovered | 0 |

### Tests

| Metric | Count |
|---|---:|
| export_eligible | 1 |
| needs_review | 1 |
| rejected | 1 |
| total | 3 |
| valid | 1 |

### Source Chunks

| Metric | Count |
|---|---:|
| covered | 1 |
| total | 3 |
| uncovered | 1 |
| with_requirements | 2 |
| without_requirements | 1 |

## Coverage Gaps

- Uncovered requirements: req_002
- Uncovered obligations: none

## Conflicts

- req_002: The bot may show order status without asking for an order number. Conflicts with: req_001

## Approval Needed

- None

## Blocked Obligations

- obl_002 (blocked_unclear_requirement) for req_002: Conflicting requirement must be resolved before testing.

## Rejected or Non-Exportable Tests

- tc_002 (rejected, export_eligible=False): Unknown obligation is rejected. Reasons: unknown obligation obl_missing
- tc_003 (needs_review, export_eligible=False): Conflicting order status path needs review. Reasons: conflicting requirement req_002; non-exportable obligation obl_002
