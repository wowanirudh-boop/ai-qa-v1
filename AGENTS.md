# Agent Directives

## Working Rules

- State assumptions and success criteria before coding.
- Implement one component at a time.
- Keep changes surgical and directly tied to the request.
- Use TDD for every implementation component.
- Do not broaden scope or implement future components.

## Hard Architecture Rules

1. Do not generate test cases directly from raw documents.
2. All test generation must flow through `AtomicRequirement` and `TestObligation`.
3. Code owns orchestration, schemas, validation, persistence, IDs, state, deduplication, coverage, and export eligibility.
4. Runtime skills own LLM reasoning only.
5. No subsystem may call an LLM directly except through the Skill Runtime.
6. Every validated `AtomicRequirement` must have `source_refs` unless its `origin` is explicitly `inferred`, `assumption`, `user_added`, or `system_default`.
7. Every `TestCase` must have `requirement_ids` and `obligation_ids`.
8. Reject orphan test cases.
9. Maintain traceability: `SourceChunk -> Requirement -> Obligation -> TestCase`.
10. Every component must be independently testable.
11. Every component must have unit tests and, where useful, golden fixtures.
12. Use strict data contracts.
13. Use TDD for every component.
14. Do not implement future components unless explicitly asked.
15. Build v1 as a modular monolith with CLI and local JSON artifacts.
