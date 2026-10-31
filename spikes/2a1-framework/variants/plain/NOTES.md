# `plain` variant: notes (task F1)

Plain Python baseline of spec section 1: standard library + `pydantic` (already a runtime dependency of lfmap-core), Ollama through `common/ollama.py` (`urllib`, proxies ignored), state in one JSON file per run. Code: `flow.py` only.

## How the contract maps to the code

- `run_flow`: Plan (skipped when `replay_cards` is given) -> `work_batch` over all cards -> `review_batch` over all cards -> one more `work_batch` + `review_batch` for the cards with `rework`; a second `rework` becomes `escalate`. Every phase is a plain loop over the cards, so each model is loaded once per phase (E7). Gate retries (max 2 rounds) stay inside the Work phase, on the same Working model.
- Approval pause: `pause` writes `state.json` (the pydantic `State`), `reports.json` (`RunRecord`) and `awaiting_approval.json` into `<state_dir>/<run_id>/` and returns; the process can exit.
- `resume`: a new process reads `state.json`, refuses a run that is not awaiting approval, writes `done.json`. No server, no daemon, no account (E4, E6).
- `invalid_json` from the Leading model is recorded in the report and becomes `escalate` for approval; a card whose Work produced no code is escalated without a review call.

## Measures

| Id | Value | How it was measured |
| --- | --- | --- |
| S1 | **135** lines (32 of them imports) | `common.metrics.folder_lines(variants/plain)`: non-blank, non-comment, non-docstring lines |
| S3 | **69** lines of test glue, all shared; **0** variant-specific | `tests/contract_fixture.py` (58) + `tests/conftest.py` (11). `FakeModel` is used as the `ChatModel` directly, no adapter |
| S5 | **0** framework concepts | Uses only `pydantic.BaseModel` (for `State`), already used across lfmap; no framework class or decorator |
| S2, E8 | 0 new runtime packages | the variant needs nothing beyond the spike's default group (`pydantic`) |

Contract test (`tests/test_variant_contract.py`, 8 tests for `plain`): all pass offline under the socket guard; the guard recorded no non-loopback connection. The `plain` part takes about 12 s on the cloud Linux container, most of it in the gate subprocesses (pytest, ruff); the run -> exit -> `resume` subprocess test about 4 s. S4 (overhead in a real run) and import time come from `run.py` metrics in F4.

## Numbering of the result ADR

The handoff and spec call the spike's result ADR "ADR-023". That number is now taken: ADR-023 is "agents run under a separate Windows account" (accepted 2026-10-30). In spike documents the result ADR is **ADR-024 (proposed number)**; the handoff itself is not edited. The F5 report should use ADR-024 too and list the renumbering in its PR body.
