You are a careful Python 3.12 developer. Write ONE new module in the `lfmap` monorepo: `packages/lfmap-core/src/lfmap_core/flows_refs.py` (task FL-1 of `docs/handoff/2026-11-06-lfmap-flows.md`, spec section 4 (references) of `docs/specs/flows.md`). Code, comments and docstrings in English. Standard library, pydantic and `lfmap_core` only. Small functions, type hints everywhere.

RULES
- Do NOT edit the tests; the frozen tests are `packages/lfmap-core/tests/test_flows_refs.py`.
- Keep the module small; the Flows line stays plain Python (ADR-024), no framework.
- Paths that an operation caller supplies go through the permission checks of `lfmap_core` before any file-system call. Paths the module derives from its own configuration (the flows.toml location) are not caller-supplied. The module reads no environment variable or clock outside what the spec names.

This case reviews a copy of the real module as merged in PR #173 (written by a Sonnet Working session, not by qwen); there is no Plan run. The card gives no API listing: the Leading review judges the module against the spec section and the rules above.
This copy carries one seeded bug.
