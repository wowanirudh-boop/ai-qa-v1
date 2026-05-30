# Codex Workflow

Future implementation should happen one component per chat.

1. Open a new chat for each component.
2. Tell Codex to read `AGENTS.md` and the relevant component spec under `docs/components/`.
3. Implement only that component.
4. Follow `docs/TDD_RULES.md`.
5. Run tests.
6. Summarize files changed, tests added, commands run, assumptions, and non-goals.

## Standard Prompt Pattern

```text
Read AGENTS.md, docs/TDD_RULES.md, docs/DATA_CONTRACTS.md, and docs/components/CXX_name.md.
Implement only CXX.
Use TDD.
Do not implement future components.
Run the relevant tests and summarize the result.
```

## Required Final Summary

Each implementation chat should summarize:

- Files changed
- Tests added or updated
- Commands run
- Assumptions
- Non-goals
- Any known gaps or follow-up risks

