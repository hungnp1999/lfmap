You are a careful Python 3.12 developer. Write ONE new module in the `lfmap` monorepo: `packages/lfmap-core/src/lfmap_core/flows_triggers.py` (task FL-3 of `docs/handoff/2026-11-06-lfmap-flows.md`, spec section 6 (triggers) and the `flows.run.<status>` events of section 5 of `docs/specs/flows.md`). Code, comments and docstrings in English. Standard library, pydantic and `lfmap_core` only. Small functions, type hints everywhere.

RULES
- Do NOT edit the tests; the frozen tests are `packages/lfmap-core/tests/test_flows_triggers.py`.
- Keep the module small; the Flows line stays plain Python (ADR-024), no framework.
- Caller-supplied paths go through the permission checks of `lfmap_core` before any file-system call; the module reads no environment variable or clock outside what the spec names.

This case reviews the real module as merged in PR #176 (written by a Sonnet Working session, not by qwen); there is no Plan run. The card gives no API listing: the Leading review judges the module against the spec section and the rules above.
