# `pydanticai` variant: notes (task F2)

PydanticAI variant of spec section 1: `pydantic-ai-slim[openai]==2.60.0`, driving model calls through PydanticAI `Agent` backed by a `FunctionModel` that delegates to `ChatModel`. State is serialized as `state.json` per run. Code: `flow.py` only.

## How the contract maps to the framework

- `run_flow`: Model calls in each phase (Plan, Work, Review) are orchestrated through PydanticAI `Agent` instances with `FunctionModel`. The `FunctionModel` maps `ModelRequest` (`SystemPromptPart`, `UserPromptPart`) to the `ChatModel.chat(system, user, schema)` protocol, returning `ModelResponse` with `TextPart`.
- Batch-phase order (E7): Because `Agent` is invoked synchronously per step (`agent.run_sync(...)`), batching is expressed naturally as loops within phase functions (`plan`, `work_batch`, `review_batch`). No framework resistance or unexpected interleaving occurred; Ollama model swaps remain minimal (leading -> working -> leading -> working -> leading).
- Approval pause: PydanticAI provides no built-in pause/resume or durable checkpointing across process exits. The pause is handled by saving `state.json` (`State`), `reports.json` (`RunRecord`), and `awaiting_approval.json` into `<state_dir>/<run_id>/`, allowing the process to terminate cleanly (E4, E6).
- `resume`: A fresh process loads `state.json`, checks `status == "awaiting_approval"`, updates the status to approved or rejected, and writes `done.json` (E4).
- Observability and network guard (E2): PydanticAI outputs a brief startup notice to stderr when observability is unconfigured, but attempts zero network connections without explicit OpenTelemetry/Logfire endpoints. The socket guard recorded 0 non-loopback connections.

## Measures

| Id | Value | How it was measured |
| --- | --- | --- |
| S1 | **162** lines | `common.metrics.folder_lines(variants/pydanticai)`: non-blank, non-comment, non-docstring lines |
| S3 | **69** lines of test glue, all shared; **0** variant-specific | `tests/contract_fixture.py` (58) + `tests/conftest.py` (11). `FakeModel` is wrapped transparently via `FunctionModel`, so no `testing.py` or variant-specific test glue was needed |
| S5 | **9** framework classes, **0** decorators | Classes: `Agent`, `FunctionModel`, `AgentInfo`, `ModelMessage`, `ModelRequest`, `ModelResponse`, `SystemPromptPart`, `UserPromptPart`, `TextPart` (all from `pydantic_ai`) |
| S2, E8 | **21** new runtime packages, **27.93 MB** installed size | Extra packages over default group (`pydantic` + dev): `pydantic-ai-slim` (8.52 MB), `openai` (9.03 MB), `tiktoken` (2.39 MB), `genai-prices` (1.62 MB), `regex` (1.15 MB), `griffelib` (0.65 MB), `charset-normalizer` (0.59 MB), `anyio` (0.51 MB), `jiter` (0.49 MB), `httpx2` (0.44 MB), `logfire-api` (0.43 MB), `urllib3` (0.43 MB), `idna` (0.37 MB), `httpcore2` (0.29 MB), `certifi` (0.23 MB), `requests` (0.22 MB), `opentelemetry-api` (0.19 MB), `pydantic-graph` (0.18 MB), `h11` (0.10 MB), `truststore` (0.06 MB), `sniffio` (0.02 MB). Passes E8 (limit 25 packages) |

Contract test (`tests/test_variant_contract.py`): 68 passed, 8 xfailed (remaining xfails belong to the unimplemented `langgraph` variant F3). All 8 contract tests for `pydanticai` pass offline under `SocketGuard` with no blocked connections.
