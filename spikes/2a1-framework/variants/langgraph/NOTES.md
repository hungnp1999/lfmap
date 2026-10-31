# `langgraph` variant: notes (task F3)

LangGraph variant of spec section 1: `langgraph==1.2.16` with `langgraph-checkpoint-sqlite==3.1.2` (`langchain-ollama==1.1.0` is pinned in the group but not imported: the fakes and `ChatModel` are called from plain node functions). Code: `flow.py` only.

## How the contract maps to the framework

- `run_flow`: a `StateGraph` with nodes `plan -> work -> review -> (work | pause) -> approval -> END`. A conditional edge after `review` sends the cards with verdict `rework` back to `work` once (`REVIEW_ROUNDS = 2`); the second rework becomes `escalate` inside the `review` node. `invalid_json` becomes `escalate`, a card without a diff gets an `escalate` report without a review call, replay cards skip Plan and their first Work round (all as in `plain`).
- Batch-phase order (E7): each node loops over all pending cards, so the trace is L, W x3, L x2, W, L with no extra effort. A graph node is a unit of batching, which fits the "all Plan, all Work, all Review" rule better than per-card fan-out (`Send`) would; fan-out would have needed explicit ordering.
- Approval pause: node `approval` calls `interrupt("awaiting_approval")`. The graph runs with `SqliteSaver` on `<state_dir>/<run_id>/checkpoints.sqlite`, `thread_id = run_id`. The `pause` node (before `approval`) writes `reports.json` and `awaiting_approval.json`; `approval` writes `done.json` after the answer. The interrupt needs its own node: LangGraph re-runs the whole node that raised it on resume, so side effects must not share it.
- `resume`: a new process opens the checkpoint file, rebuilds the graph without models (no model node runs after the pause), checks `get_state().next == ("approval",)` (else `ValueError`, so a second resume of a finished run fails), then `invoke(Command(resume=approve))`.
- Graph state holds the run as one JSON dict (`State.model_dump(mode="json")`) plus `pending`, `feedback`, `review_round`. Putting pydantic models directly in the state was not tried: the checkpoint serializer would need to know the classes, and the dict keeps the file readable.
- Models and `state_dir` are captured by a closure in `build_graph`, not stored in the state (they are not serializable).
- Network guard (E2): importing `variants.langgraph.flow` and all 8 contract tests ran under `SocketGuard` with 0 non-loopback connections and no environment variable set; `langsmith` is installed (dependency of `langchain-core`) but did not send anything because tracing is off by default.

## Measures

| Id | Value | How it was measured |
| --- | --- | --- |
| S1 | **187** lines | `common.metrics.folder_lines(variants/langgraph)`: non-blank, non-comment, non-docstring lines |
| S3 | **80** lines of test glue, all shared; **0** variant-specific | `tests/contract_fixture.py` (69) + `tests/conftest.py` (11), non-blank lines. No `testing.py` was needed: nodes call `ChatModel.chat` directly |
| S5 | **7** framework classes/functions, **0** decorators | `StateGraph`, `START`, `END`, `Command`, `interrupt` (from `langgraph.graph` / `langgraph.types`), `SqliteSaver` (`langgraph.checkpoint.sqlite`), plus the compiled graph's `invoke` / `get_state` and `add_node` / `add_edge` / `add_conditional_edges` / `compile` methods |
| S2, E8 | **38** new runtime packages over the default group (`pydantic` + dev), **44.52 MB** installed; **31** packages / **42.73 MB** not shared with the `pydanticai` group | Closure of `langgraph`, `langchain-ollama`, `langgraph-checkpoint-sqlite` over `pydantic`, sizes from the installed files. Largest: `zstandard` (23.87), `langsmith` (3.84), `pyyaml` (2.90), `langchain-core` (2.47), `xxhash` (1.09), `langgraph` (1.08), `uuid-utils` (0.88), `websockets` (0.84), `charset-normalizer` (0.76), `langgraph-sdk` (0.73), `ormsgpack` (0.56). **Fails E8** (limit 25 packages). Without `langchain-ollama` (`ollama`, `langchain-core` and its tree) the count would still be above 25 |

Contract test (`tests/test_variant_contract.py`): all 24 `langgraph` cases pass offline; whole spike suite `uv run --group langgraph --group pydanticai pytest -q`: 76 passed, 0 xfailed.

## Friction (E7)

- Nodes get the whole state and must return a partial update, so every node does `State.model_validate` / `model_dump` on the dict; this is most of the glue.
- `interrupt` semantics (node restarts from its top on resume) forced the `pause` / `approval` split.
- Resume has no "is it paused" API beyond `get_state().next`; a missing checkpoint file must be tested by hand, because `sqlite3.connect` would silently create an empty database.
