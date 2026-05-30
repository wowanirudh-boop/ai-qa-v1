# TDD Rules

Every implementation component must be built test-first.

## Required Process

1. Read `AGENTS.md`.
2. Read the component spec under `docs/components/`.
3. Identify input and output data contracts from `docs/DATA_CONTRACTS.md`.
4. Write tests first.
5. Include happy path tests.
6. Include validation failure tests.
7. Include traceability tests where applicable.
8. Include golden fixture tests where the component transforms artifacts.
9. Run tests and confirm they fail for missing functionality when practical.
10. Implement the smallest code needed.
11. Run tests again.
12. Refactor only after tests pass.
13. Do not broaden the component scope.
14. Do not implement future components.

## Required Test Categories

- Schema contract tests
- Artifact transformation tests
- Traceability tests
- Invalid input tests
- Status transition tests
- CLI smoke tests where applicable
- Golden fixture tests where useful

## Component Test Expectations

Each component must be independently testable. Tests should prove that the component accepts only its documented input contracts and writes only its documented output contracts.

Where a component transforms one artifact into another, include at least one golden fixture that shows the input JSON and expected output JSON. Golden fixture tests should compare stable content, not timestamps or incidental formatting.

## Scope Control

Tests should enforce the component boundary. If a component must not generate tests, call runtime skills, export packages, or mutate validation state, add tests or assertions that make that boundary clear when practical.

