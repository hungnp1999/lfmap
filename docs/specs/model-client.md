# Module Spec: ModelClient (model access in `lfmap-core`) and the thin `llm` plugin

- Package: `lfmap-core` (flat modules next to `events.py`), plugin `plugins/lfmap-llm`
- Issue: #189 (decision 1 of the architecture review, `docs/research/2026-11-08-architecture-review.md` C1 and K2). Folds RT-08 (#167).
- Roadmap: Phase 2, "Agent Router" = the routing policy of this spec (Blueprint §4.4, `docs/reference/blueprint-section-4.md`).
- Related: `docs/specs/knowledge.md` (embedder, Ollama), `docs/specs/chat-ui.md` §2 (planned model loop), `docs/specs/flows.md` (a flow calls `llm.*` like any operation), ADR-009/017/018 (tiers, gate), ADR-020 (`min_tier`), ADR-016 (own `data_dir` is not a side effect).
- Status: draft for owner review. Docs only; code comes in a later PR that implements the frozen tests of section 10.

## 1. Purpose

One place in the core that talks to language models. Today there are three separate clients heading in three directions: `lfmap_knowledge/embed.py` (Ollama native `/api/embed`), the model loop planned in `chat-ui.md` §2, and the OpenAI-compatible embedder client of RT-08. Whether a call stays local or goes to a cloud endpoint is a security boundary (egress, `cloud_ai`, `[approval.destinations]`, T3), so it belongs next to the Permission Manager and the approval gate, not inside each plugin.

Goals:

- A `ModelClient` Protocol with `chat` and `embed`, and one implementation for OpenAI-compatible HTTP APIs on the standard library.
- Loopback by default. A cloud endpoint is reachable only by explicit routing in `config.toml` and only through the gate (T3) and an egress record.
- Routing policy as data in `config.toml` (Blueprint §4.4): which task goes to which endpoint.
- Plugins reach it through `ctx.models`, as they reach events through `ctx.events`.
- A thin `llm` plugin (`summarise`, `extract`, `classify`) exposes it to CLI, MCP and Flows with no plugin-specific code in any adapter.
- `knowledge` moves its embeddings onto it only after the vectors are shown to be equivalent on the iso-vi bench (section 8).

Non-goals (this spec): streaming, tool calling and function calling, multimodal input, fine-tuning, an agent loop, cost accounting, retries across endpoints (no automatic fallback from local to cloud, ever), a model download or install helper, a UI. The chat loop of `chat-ui.md` will be built on this layer later.

## 2. Modules

| Module | Content |
| --- | --- |
| `models.py` | `ChatMessage`, `ChatResult`, `ModelClient` Protocol, `ModelEndpoint`, `ModelsConfig` (pydantic, `extra="forbid"`), `load_models_config(config)` |
| `models_http.py` | `OpenAICompatibleClient`: `POST {base_url}/chat/completions` and `/embeddings`, stdlib `urllib.request`, no proxy, no redirects |
| `models_router.py` | `ModelRouter`: resolves a task to an endpoint, applies the data-class rules, calls the gate, writes the egress record, returns a `ModelClient` view bound to one call |
| `models_egress.py` | `egress()` append-only writer for `egress.jsonl` (section 6) |
| `tool.py` | `ToolContext.models` property (like `events`): the router bound to this plugin, channel and approver |
| `runtime.py` | `build_tool` and `context_for` attach the router when the manifest has `[adapters] models = true` |
| `plugins/lfmap-llm` | `Tool` class with `summarise`, `extract`, `classify` |

Standard library and pydantic only. No new dependency. Adapters (`cli.py`, `mcp_adapter.py`, REST) are not touched: the `llm` operations are generated from its manifest like every other plugin.

## 3. The Protocol

```python
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatResult(BaseModel):
    text: str
    model: str
    finish_reason: Literal["stop", "length", "other"]
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ModelClient(Protocol):
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> ChatResult: ...
    def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]: ...
```

Rules every implementation keeps:

- `embed` returns exactly one vector per text, in input order, and raises `backend_unavailable` (`reason: bad_response`) if the count differs (the `count` seed class of F7). An empty list returns an empty list without a request.
- `chat` with `temperature = 0.0` is the default; there is no hidden system prompt.
- Limits: at most 200 000 characters of message content per call, `max_tokens` at most 8192, embed batches of at most 1024 texts (the existing `MAX_BATCH_SIZE`), 120 s timeout. Over a limit is `invalid_input`.
- Errors are `ToolError` only: `invalid_input` (limits, bad config), `permission_denied` (gate), `backend_unavailable` with `reason` in `unreachable`, `http_<code>`, `bad_response`, `timeout`. The response body in details is cut to 500 characters and never contains the request.
- `json_mode = True` asks the endpoint for a JSON object (`response_format`); the client still returns text and does not parse it. Parsing and validation belong to the caller (`extract`).

`ModelClient` is the plugin-facing type. The object a plugin gets from `ctx.models` is a `ModelRouter` view with the same two methods plus a required `task` (section 4), so a plugin cannot name a URL.

## 4. Routing policy (the Agent Router as data)

Configured in the user's `config.toml`; no operation writes it (same rule as folders).

```toml
[models.endpoints.local]
kind = "local"                       # local | cloud
base_url = "http://127.0.0.1:11434/v1"
chat_model = "qwen3:14b"
embed_model = "bge-m3"

[models.endpoints.cloud]
kind = "cloud"
base_url = "https://api.example.com/v1"
chat_model = "..."
api_key_env = "LFMAP_CLOUD_API_KEY"  # name of an environment variable, never the key

[models.routes]                      # task -> endpoint name
embed = "local"
summarise = "local"
extract = "local"
classify = "local"
review = "cloud"                     # a task the owner chose to send out
default = "local"
```

Rules:

1. A `kind = "local"` endpoint must have a loopback host (`localhost` or a loopback IP, no user info, `http` or `https`), checked with `urllib.parse` and `ipaddress` exactly like `check_loopback` today; otherwise `invalid_input` when the config is loaded. This is the "loopback by default" invariant.
2. A `kind = "cloud"` endpoint must use `https`. It is reachable only when a route names it. There is no fallback: an unreachable local endpoint is an error, never a silent switch to cloud.
3. A route names an endpoint that exists, else `invalid_input`. A task without a route uses `routes.default`; with no `[models]` table at all, the built-in default is one local endpoint at `http://127.0.0.1:11434/v1` with the models `knowledge` uses today, so nothing changes for a user who does nothing.
4. Data class decides what may be sent (Blueprint §4.4 row 1): `secret` never leaves, so a `secret` call to a cloud endpoint is `permission_denied` before the gate is asked. `private` and `normal` to a cloud endpoint go through the gate (section 5). Local endpoints accept any class.
5. The caller states the data class of what it sends (`normal` default). A plugin cannot lower a class that the data itself carries (for example `knowledge` content from a `secret` root is `secret`); how the class travels with data is an open question (Q3).
6. `embed` is always routed like any other task. The Blueprint says embeddings are local, so a config that routes `embed` to a cloud endpoint is refused unless `[models] allow_cloud_embed = true` (open question Q4).

## 5. The gate for cloud endpoints

A call to a `kind = "cloud"` endpoint, from `ModelRouter`, before any socket is opened:

1. The plugin's manifest must declare `[permissions] cloud_ai = true` and `network = true`; otherwise `permission_denied`.
2. `ctx.require_approval("external", "send text to a cloud model", detail, destination=<host>, data=<class>)`: tier **T3**. A preapproved `[approval.destinations."<host>"]` entry (not expired, data level high enough, never `secret`) covers the call as today; otherwise T3 asks a person at a TTY and is refused on `mcp`, `rest`, `job`, `event` and `flow` (existing `decide` rules). Nothing in this spec adds a way around T3.
3. `--yes`, `--approve`, MCP elicitation and grants keep the existing meaning: they never cover T3 except the existing time-limited grant and destination preapproval.
4. On refusal nothing is sent and no egress record is written (the refusal is in `audit.jsonl` already).

A local endpoint needs `permissions.network = true` and `ctx.permissions.require_network()` (loopback only), and no approval.

Tier of an `llm` operation. Its manifest declares `side_effects = "external"` with `min_tier = "T0"`; `Tool.call_tier(operation, input, settings)` returns T0 when the task routes to a `local` endpoint and T3 when it routes to a `cloud` endpoint (ADR-020). In a flow or a job, a cloud route therefore becomes a `flows.resume` or job proposal, which a person approves at a TTY; a local route runs unattended.

## 6. Egress record

Every call that reaches a cloud endpoint, whether it succeeds or fails after the request is sent, appends one JSON line to `%LOCALAPPDATA%\lfmap\egress.jsonl`:

```json
{"time": "...", "principal": "owner", "channel": "cli", "plugin": "llm", "operation": "summarise",
 "task": "summarise", "endpoint": "cloud", "host": "api.example.com", "model": "...",
 "data": "normal", "bytes_out": 1234, "bytes_in": 567, "status": "ok"}
```

- Only the listed fields are accepted (an allow-list like `AUDIT_FIELDS`); message content, prompts, vectors and API keys never appear.
- Local calls are not logged here (nothing leaves the machine); the call is still visible in the plugin's own results.
- The `knowledge` `egress_log` table (content returned to MCP/REST clients) is a different thing and stays as it is.
- A failure to write the line fails the call before the request is sent (log first, then send; the final line with sizes is appended after). Whether this is one file for both lines or two is open question Q5.

## 7. The `llm` plugin

`plugins/lfmap-llm`, id `llm`, `[adapters] cli = true, mcp = true, rest = false, events = true`, `[permissions] network = true, cloud_ai = true`, `fs_read = []`, `fs_write = []`. It reads no files: callers pass text (a flow step passes the output of `markitdown.convert`). All three operations have `side_effects = "external"` with `min_tier = "T0"` (section 5).

| Operation | Input | Output |
| --- | --- | --- |
| `summarise` | `{text, max_words = 150, language = "same", data = "normal"}` | `{summary, model, truncated}` |
| `extract` | `{text, schema, data = "normal"}` where `schema` is a JSON object of field name to `{type: string\|number\|boolean\|list, description}` | `{fields, missing, model}` |
| `classify` | `{text, labels: list[str] (2 to 20), data = "normal"}` | `{label, model}` |

Behaviour:

- Prompts are fixed in the plugin (English instructions, any input language). The input text is placed after a delimiter and the system message says it is data, not instructions. This reduces, and does not remove, prompt injection; the result of `extract` and `classify` is therefore always validated by code.
- `extract` asks for JSON, parses it, and keeps only keys in the schema with the declared type; wrong or absent fields go to `missing`. Unparsable output is `backend_unavailable` (`reason: bad_response`). `classify` returns exactly one of `labels` or `invalid_input`-style `backend_unavailable` (`bad_response`); it never returns a free-text label.
- `summarise` input longer than the limit is cut at a paragraph boundary and `truncated = true`; the plugin does not chunk and re-summarise in v1.
- Output is capped by `max_tokens`; the plugin writes nothing to disk (its own `data_dir` is unused in v1).
- The operations are usable from CLI (`lfmap llm summarise ...`), MCP (`llm_summarise`) and as a flow step (`call = "llm.summarise"`) with no adapter change.

## 8. Moving `knowledge` onto it, and RT-08

`knowledge` keeps `OllamaEmbedder` until the evidence below exists. The switch is a separate, later PR.

Equivalence check (this is also RT-08's acceptance):

1. Same model (`bge-m3`), same texts: the 30 synthetic documents of `packages/lfmap-knowledge/bench/iso-vi` chunked as the indexer does, plus a 500-text sample.
2. Embed through Ollama native `/api/embed` (today) and through the OpenAI-compatible `/v1/embeddings` of the same Ollama. Record per-vector cosine similarity, vector length (1024) and whether the vectors are normalised.
3. Repeat against `llama-server` serving the bge-m3 GGUF in a CPU container (the RT-08 target), as an information row, not a gate.
4. Run the iso-vi bench (9 questions) on an index built with each path.

Pass to switch: every vector has cosine ≥ 0.9999 with the old one (RT-08 asked for ≥ 0.99; the issue says "identical", so the stricter number is proposed, Q6), the dimension is equal, and the bench shows the same gold files in the same top-10 for all 9 questions with `precision` and token counts not lower than the recorded ones. If only the bench passes and cosine does not, the old vectors stay in use and a full reindex is a separate owner decision (existing vectors would be mixed with new ones).

After the switch: `knowledge` settings `ollama_url`, `embed_model`, `embed_batch`, `embed_concurrency` keep working (read as fallbacks for the `embed` route); `OllamaEmbedder` is removed in the same PR; `knowledge.status` keeps `ollama_ok`. The existing keyword fallback when the embedder is down (`mode_used = "keyword"`) is unchanged. `knowledge` declares `[adapters] models = true`.

Smoke on DIEP-ANH with Ollama is `res:Local` and happens after the code PR, before the `knowledge` switch.

## 9. Security and invariants (for `ARCHITECTURE.md` when the code lands)

- No network beyond loopback by default: a model endpoint is loopback unless the owner wrote a `cloud` endpoint and a route to it; each cloud call is T3 and writes an egress line. (This replaces "No network beyond loopback" with "…except a cloud route through the gate"; the text change belongs in the code PR.)
- Proxy environment variables are ignored (`ProxyHandler({})`); redirects are refused (a redirect could move data to another host); `https` verifies certificates with the default context, never disabled; no credentials in URLs.
- The API key comes from the environment variable named in config, is sent only in the `Authorization` header to its own endpoint, and appears in no log, error, audit or egress line.
- A plugin names a task, not a URL or an endpoint; it cannot read the routing table.
- `config.toml` is never written by any operation; routes and endpoints change only by the owner editing the file.
- Fields in audit and egress lines are allow-listed; content never lands there.
- Untrusted text: model output is data. No operation executes, fetches or writes based on model output without a further gate; `extract` and `classify` validate against caller-provided structure.
- The code PR touches network calls, so `/security-review` runs before merge (issue label `security-review`).

## 10. Frozen tests (to implement with the code; written first)

Location when the code starts: `docs/specs/model-client-tests/`, copied unchanged into `packages/lfmap-core/tests/` (and `plugins/lfmap-llm/tests/` for the plugin). Names are fixed here so the Planner can freeze them.

The four required by Card A:

| Test | Asserts |
| --- | --- |
| `test_protocol_conformance_fake_server` | `OpenAICompatibleClient` against a stdlib `http.server` thread: `chat` sends the expected body (`model`, `messages`, `temperature`, `max_tokens`) and returns `ChatResult`; `embed` returns one vector per text in order; a response with the wrong vector count raises `backend_unavailable` with `reason: bad_response`; a closed server raises `backend_unavailable` (`unreachable`); the object satisfies `ModelClient` (`typing.runtime_checkable` or structural check) |
| `test_non_loopback_refused_without_approval` | a `local` endpoint with host `10.0.0.5` or `api.example.com` is `invalid_input` at config load; a `cloud` route called through a `Gate` with no approval (`channel` `mcp`, `job`, `flow`) raises `permission_denied` and opens no socket (a socket guard fixture fails the test on any connect) |
| `test_egress_line_per_cloud_call` | with an approved destination, one cloud `chat` and one cloud `embed` append exactly two lines to `egress.jsonl` with only allow-listed fields, correct `host`, `data`, `bytes_out > 0`; a local call appends none; the prompt text and the API key do not appear in the file |
| `test_routing_by_config` | tasks map to endpoints as configured; unrouted task uses `default`; no `[models]` table gives the built-in local endpoint; a route to an unknown endpoint is `invalid_input`; unreachable local endpoint does not fall back to cloud |

Further tests of this spec:

| Test | Asserts |
| --- | --- |
| `test_secret_never_to_cloud` | `data = "secret"` to a cloud endpoint is `permission_denied` even with a preapproved destination; nothing is sent |
| `test_private_needs_destination_level` | `private` to a destination preapproved for `normal` only is not covered and asks (T3) |
| `test_cloud_requires_manifest_permissions` | a plugin without `cloud_ai = true` cannot reach a cloud route |
| `test_no_redirect_no_proxy` | a 302 from the fake server is `backend_unavailable`, not followed; `HTTPS_PROXY` in the environment is ignored |
| `test_api_key_only_in_header` | the key from `api_key_env` reaches the server in `Authorization` and appears in no `ToolError`, audit or egress line; a missing variable is `invalid_input` naming the variable, not its value |
| `test_limits_and_batching` | oversize content, `max_tokens` > 8192 and batches > 1024 are `invalid_input`; an empty `embed` sends nothing |
| `test_ctx_models_gate` | `ctx.models` exists only with `[adapters] models = true` (else `permission_denied`); a plugin cannot pass a URL |
| `test_call_tier_follows_route` | `llm.summarise` is T0 on a local route and T3 on a cloud route; in a flow with `max_tier` 0 or 1 the cloud route pauses behind a `flows.resume` proposal |
| `test_llm_extract_validates` | `extract` drops keys not in the schema, moves wrong-typed fields to `missing`, and rejects non-JSON output with `bad_response` |
| `test_llm_classify_label_set` | `classify` never returns a label outside `labels` |
| `test_llm_prompt_delimits_input` | the request body puts the input after the delimiter and the system message marks it as data |
| `test_embed_equivalence_bench` | marked `local`, skipped in CI: cosine ≥ 0.9999 between native `/api/embed` and `/v1/embeddings` on the bench sample, and equal top-10 on the 9 iso-vi questions (section 8) |

CI stays offline: every test above except `test_embed_equivalence_bench` uses the fake server and a socket guard.

## 11. Task breakdown (proposal)

| Task | Content |
| --- | --- |
| MC-1 | `models.py`, `models_http.py`, config model, the four required tests |
| MC-2 | `models_router.py`, `models_egress.py`, gate and egress tests, `ctx.models`, `ARCHITECTURE.md` invariant text |
| MC-3 | `plugins/lfmap-llm`, `call_tier`, plugin tests, flow-step test |
| MC-4 | equivalence run on DIEP-ANH (`res:Local`), report in `docs/research/` |
| MC-5 | `knowledge` onto `ModelClient`, remove `OllamaEmbedder` (only if MC-4 passes) |

MC-1 to MC-3 are Cloud work with `/security-review`; MC-4 needs Ollama on pc-01. Each task is one issue/PR on the board.

## 12. Open questions for the owner

1. **Config shape.** Are `[models.endpoints.*]` plus `[models.routes]` acceptable, or do you want routes keyed by data class as well (for example `private → local`, `normal → cloud` for `review`)? This spec routes by task and then checks the data class.
2. **API keys.** The key is read from an environment variable named in config. Is that enough for a personal setup, or do you want it stored in Windows Credential Manager? (Credential Manager would add a dependency or a `ctypes` shim; I would not add it in v1.)
3. **Data class provenance.** `knowledge` knows a root is `secret`, `private` or `normal`, but a flow only sees text. Should the class travel with a step output (a flow-level label), or does the caller state it per call as in this draft? The draft trusts the caller, which is weaker than you may want for cloud routes.
4. **Cloud embeddings.** Blueprint §4.4 says embeddings are local only. Refuse a cloud `embed` route outright (no `allow_cloud_embed` switch), or keep the switch?
5. **Egress file.** One new `egress.jsonl` for model calls (this draft) next to `audit.jsonl`, or extend `audit.jsonl` with `host`, `bytes_out`, `bytes_in` fields? Extending keeps one log but widens `AUDIT_FIELDS`.
6. **Equivalence threshold.** Cosine ≥ 0.9999 and identical top-10 (stricter than RT-08's ≥ 0.99) as the condition to switch `knowledge`, or is ≥ 0.99 with the same gold files enough? A weaker threshold means a mixed index until a full reindex.
7. **Streaming.** `chat-ui.md` will want token streaming. Leave it out of v1 and add `chat_stream` later, or include it now?
8. **Operation set.** Are `summarise`, `extract`, `classify` the right three, and should `summarise` chunk long input (map-reduce) in v1 or stay a single call with `truncated`?
9. **Model defaults.** Which local chat model should the built-in default name (the qwen card work used the Qwen family; the licence matrix is `docs/research/2026-11-06-model-licence-matrix.md`)? The draft leaves `chat_model` unset in the built-in default, so `llm` fails with a clear error until you set it.
10. **Unattended cloud calls.** In jobs and flows a cloud route always becomes a proposal. Do you want a way to preapprove one named flow for one destination (like `[approval.destinations]` but for unattended runs), or keep "a person at a TTY every time"? The draft keeps the latter.
11. **ADR wording.** The invariant "no network beyond loopback" gains an exception for gated cloud routes. Do you want a new ADR (or an amendment to the cloud/egress ADRs) before the code PR, since ADR text lives outside the repo?
