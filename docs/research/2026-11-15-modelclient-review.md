# ModelClient: post-merge review (MC-1 to MC-5)

- Date: 2026-11-14. Role: Reviewer. Issue #263 (item K7 of the 11/11 report). Requested by Hùng.
- Scope: `models.py`, `models_http.py`, `models_router.py`, `models_egress.py`, the `ctx.models` wiring in `tool.py` and `runtime.py`, `plugins/lfmap-llm`, and the `knowledge` embedder after MC-5, read against `docs/specs/model-client.md`. Analysis only; no code is changed by this file.
- State reviewed: `main` at `8abaa15` (PRs #221, #225, #226, #283 merged).
- Method: reading the code and the spec, running the existing tests (40 pass: `test_models.py`, `test_models_router.py`, `plugins/lfmap-llm/tests`), and two throwaway probe scripts in a Cloud checkout against a fake loopback server. A finding marked **probe** was reproduced; **read** means it follows from the code and should get a test when it is fixed. The probe scripts are not committed. No real model was called: Cloud cannot reach Ollama, so everything about real model behaviour is marked **unverified**.

## 1. Verdict

The security boundary holds. With the default configuration no call can leave the machine, and I found no way for a plugin to reach a cloud endpoint without the owner's route, the manifest permissions, the `secret` refusal and a T3 approval. The implementation follows the spec closely and is small.

There is **one defect that affects use today**: after MC-5, `knowledge reindex` can stop building vectors for good on documents with long paragraphs or tables, and the only sign is `embed_skipped_reason = "invalid_input"` (F1). It should be fixed first.

Everything else is either dormant until the first cloud route is enabled (F2, F3, F4, F7), a quality gap in the `llm` plugin that needs one real run on pc-01 to size (F5, F6), or minor (F8 to F11). The cloud findings should be closed **before** DC-6 (#237) removes `allow_cloud_unlabelled`, because that is the moment they become reachable.

| # | Finding | Evidence | Affects | Priority | Issue |
| --- | --- | --- | --- | --- | --- |
| F1 | `knowledge reindex` never embeds when a batch of 128 chunks exceeds 200 000 characters | probe | local use today | P1 | #296 |
| F2 | A cloud `llm` call passes two T3 gates; a preapproved destination never covers the first | probe | first cloud route | P2 | #297 |
| F3 | Egress lines are wrong in two cases: `sent` without a request, and no result line after a non-`ToolError` failure | probe | first cloud route; local error handling | P2 | #298 |
| F4 | Embeddings can go to a cloud endpoint through any task name other than `embed` | probe | first cloud route | P2 | #299 |
| F5 | `llm.summarise` returns an empty or cut-off summary as a success | probe | local use today | P2 | #300 |
| F6 | The chat path has never run against a real model; context window and thinking models are unverified | read | local use today | P2 | #301 |
| F7 | Plugin-chosen `task` and `model` and the server's `model` string reach the approval question and `audit.jsonl` unchecked | probe | first cloud route | P3 | #302 |
| F8 | `knowledge.status` now loads the embedding model on every call | probe | pc-01 GPU | P3 | #303 |
| F9 | `lfmap doctor` does not know `[models]`: fixed Ollama URL, no config check | read | owner feedback | P3 | #304 |
| F10 | Minor hardening (seven small items) | mixed | none urgent | P3 | #305 |
| F11 | Spec and `ARCHITECTURE.md` drift | read | documents | P3 | #306 |

## 2. What was checked and holds

| Check | Result |
| --- | --- |
| `local` endpoint must be loopback (`models.py:56-70`, `82-93`) | Holds. Probed 13 URL shapes: user info, `127.1`, decimal IP, `localhost.`, `0.0.0.0`, backslash and tab tricks are all refused. A fragment trick (`http://127.0.0.1#@evil.example`) passes `is_loopback_url` but the host really is `127.0.0.1`, and `ModelEndpoint` refuses the fragment |
| `cloud` endpoint must be `https`, no user info, no query or fragment | Holds |
| Cloud route refused unless `allow_cloud_unlabelled = true` (`models.py:115-119`) | Holds |
| No proxy, no redirect (`models_http.py:31-33`, `65`) | Holds; existing test `test_no_redirect_no_proxy` |
| API key only in the `Authorization` header, masked in error bodies, absent from errors and audit | Holds; existing test `test_api_key_only_in_header` |
| `secret` to cloud refused before the gate (`models_router.py:98-101`) | Holds |
| `cloud_ai` and `network` required (`models_router.py:102-108`) | Holds |
| Refused approval sends nothing and writes no `model_call` line | Holds |
| No fallback from local to cloud | Holds; `route()` only falls back to `routes.default` |
| Audit fields allow-listed; failure reason restricted by a pattern (`models_egress.py:13`) | Holds for field names; see F7 for field values |
| Malformed JSON, wrong vector count, wrong `index` values, non-finite numbers | `bad_response` |
| `call_tier` failure keeps the declared tier T3 (`runtime.py:48`) | Holds (fails closed) |
| `extract` and `classify` validate model output by code; `language` cannot carry instructions | Holds; existing tests |
| `ctx.models` only with `[adapters] models = true` | Holds |

## 3. Findings

### F1. `knowledge reindex` stops embedding on long chunks (P1, probe)

`OpenAICompatibleClient.embed` refuses a call whose texts add up to more than 200 000 characters (`models_http.py:106-107`). `ModelEmbedder` batches by count only, 128 texts by default (`indexer.py:27`, `74`). The chunker aims at 1 500 characters and allows up to 3 000 (`chunker.py:26`). A batch whose chunks average more than 1 562 characters is therefore refused before any request.

The refusal is `invalid_input`, which `_embed_batch` passes through (`indexer.py:86-87`), and `_embed` records it and stops (`indexer.py:327-329`). The failed batch and every batch after it stay pending, and the next run builds the same batch and fails the same way.

Probe: three Markdown files with 2 400-character paragraphs, fake `/v1/embeddings` server. Result: `embedded: 0`, `embed_skipped_reason: "invalid_input"`, zero requests, same on the second run. The same files with 1 200-character paragraphs embed normally (128 texts, 153 527 characters in the first request).

The old `OllamaEmbedder` had no character limit, so this is a regression of MC-5 for documents with long paragraphs or wide tables (contracts, ISO procedures). The iso-vi bench of MC-4 did not hit it. Search keeps working by keywords, so nothing looks broken.

Suggested fix: `ModelEmbedder` splits a batch by characters as well as by count (stay under the client limit), and a single text over the limit is reported by name instead of blocking the queue. Raising the limit for local endpoints is the alternative; I prefer the first because the limit is part of the Protocol (spec section 3).

### F2. Two T3 gates on a cloud `llm` call (P2, probe; dormant)

A cloud route makes `LlmTool.call_tier` return T3 (`tool.py:59-62`). Every adapter then asks the gate once for the operation, with the reason `side_effects` and no destination (`cli.py:175`, `mcp_adapter.py:96`, `flows_run.py:236`, `events_adapter.py:218`). After that the router asks again, this time with the host and the data class (`models_router.py:111-116`).

Consequences, all reproduced:

- On `mcp` with a valid `[approval.destinations]` entry the call is still denied at the first gate. The hint in the error says to "add the destination to `[approval.destinations]`", which the owner has already done.
- On the CLI the person is asked twice when no destination is preapproved. With a preapproved destination they are asked once, by the first gate, and that question names neither the host nor the data class.
- A plugin whose operations are declared T0 or T1 and that reaches a cloud route through `ctx.models` passes only the router gate, where the preapproved destination does work. The same owner configuration therefore behaves differently per plugin.

This is stricter than spec section 5 rule 2 ("a preapproved destination covers the call as today") and than `ARCHITECTURE.md` line 64, and it matches decision 10 for flows and jobs. It is not a hole. It needs a decision **[needs Hùng, at the first cloud route]**: either the router gate is the only one for model calls (then `call_tier` is used only to make a flow pause), or the operation gate stays and the documents say that preapproved destinations do not apply to `llm`. It also matters for the Lan Hài cloud intake (ADR-026), which will want unattended cloud calls to one preapproved host.

### F3. Egress lines that do not match what happened (P2, probe; dormant for cloud)

(a) The router asks for approval and writes the `sent` line before the client validates the call (`models_router.py:109-134`). Three probes (content over 200 000 characters, `max_tokens = 9000`, a cloud endpoint without `chat_model`) each produced a T3 question, a `sent` line, then `invalid_input` and an `error` line, with **zero requests**. The audit log says text was sent when nothing left the machine, and the person approved a call that could not be made. Spec section 6 defines `sent` as "appended before the request is sent".

(b) `_post` catches `HTTPError`, `OSError` and `ValueError` (`models_http.py:121-131`). `http.client.HTTPException` is none of these. Probe: a server that answers with a malformed status line raises `http.client.BadStatusLine` out of `chat`, through the router (`except ToolError` only, `models_router.py:135`), leaving a `sent` line and no result line. This breaks "errors are `ToolError` only" (spec section 3) and "one line whether it succeeds or fails after the request is sent" (section 6). On the local path the same exception would leave `knowledge reindex` with a traceback instead of the keyword fallback (**read**).

Suggested fix: validate limits and the model name before the approval (a `check` step on the client, or validation in the router); catch `http.client.HTTPException` in `_post` as `bad_response`; write the result line in a `finally`-style branch for any exception.

### F4. Embeddings can reach a cloud endpoint (P2, probe; dormant)

The rule "embeddings stay local" is enforced on the task name only: the config loader refuses a route named `embed` to a cloud endpoint (`models.py:113-114`) and the router refuses the task `embed` on a cloud endpoint (`models_router.py:96-97`). `ctx.models.embed(texts, task="review")` on a cloud route is sent. Probe: one request, `model_call` lines with `status: ok`.

The documents disagree with each other: spec section 4 rule 6 and `ARCHITECTURE.md` line 64 say embeddings never go to cloud, while the frozen test `test_model_call_audit_line_per_cloud_call` (spec section 10) expects "one cloud `embed`". The call still needs `cloud_ai`, the T3 approval and writes egress lines, so nothing leaves unseen. Decide which document is right; if the Blueprint rule stands, the router should refuse `embed()` on any cloud endpoint regardless of the task name.

### F5. `llm.summarise` returns an empty or cut-off summary as a success (P2, probe)

`summarise` ignores `finish_reason` and accepts any text (`tool.py:74-81`). Probe: an answer with empty content and `finish_reason = "length"` comes back from the router as a normal `ChatResult`, and `summarise` would return `summary = ""`. `truncated` describes the input only. In a flow the next step then works on an empty or half summary with no sign of it. `extract` and `classify` are safe here because their validation rejects such output.

Suggested fix: empty text is `backend_unavailable` (`bad_response`); `finish_reason = "length"` is reported in the output (a field, or `truncated = true` with the meaning widened in the schema description).

### F6. The chat path has not met a real model (P2, read; unverified)

MC-4 compared embeddings on pc-01. I found no record in the repo of `llm summarise`, `extract` or `classify` run against Ollama. Two behaviours cannot be checked from Cloud and can make the plugin quietly wrong:

- **Context window.** The plugin accepts 100 000 characters (`tool.py:18`). Ollama applies its own context length and, as far as I know, shortens a prompt that does not fit without an error; the OpenAI-compatible API has no field to set it. If so, a long document is summarised from a part of it while `truncated = false`. `prompt_tokens` in the answer would show it.
- **Thinking models.** With a model that reasons before answering, the reasoning may use the `max_tokens` budget. `classify` asks for 64 tokens (`tool.py:114`), so it could fail with `bad_response` every time, and `summarise` could hit F5.

Both are **unverified** and depend on the Ollama version and the model. One short smoke on pc-01 settles them (`res:gpu`, about 15 minutes): the three operations on a short and a long Vietnamese text with the Working model, recording `prompt_tokens`, `finish_reason` and the result. Do it before the acceptance scenarios (#191) use `llm` in a flow.

### F7. Unchecked strings reach the approval question and the audit log (P3, probe; dormant)

- `task` is any non-empty string (`models_router.py:88`). With a cloud `default` route every task name is routed, and the name is printed in the T3 question and stored in the audit `target`. A plugin can shape the text the person reads.
- `model` is any string a plugin passes. On a cloud endpoint the plugin, not the owner, picks the model (probe: `most-expensive-model` was sent and logged). ADR-026 expects the cheapest model and a daily cap in `[models]`; neither exists yet.
- The `model` in the result line comes from the server's answer (`models_router.py:138`), with no length or character check, so a remote party writes free text into `audit.jsonl`. Spec section 6 says no free-text field is added.

Suggested fix: `task` must match the route-name pattern (`_NAME`); a `model` override must match a short safe pattern and, on a cloud endpoint, be one the owner listed (or be refused); log the requested model, or the answered one only if it passes the same pattern. The daily cap belongs to the ADR-026 work, not here.

### F8. `knowledge.status` loads the embedding model (P3, probe)

`ping` used to be `GET /api/tags`. It now embeds the text `ping` (`indexer.py:93-99`), so every `knowledge status` makes Ollama load `bge-m3`. On pc-01, where GPU work is serial, a status call during a long model job can push the other model out of memory or wait behind it for up to 120 seconds. The new check is more truthful (it proves the model answers), so the fix is a choice: a cheap `GET {base_url}/models` through the client for `status`, keeping the real embed for `reindex`.

### F9. `lfmap doctor` does not know `[models]` (P3, read)

- `_check_ollama` asks `http://localhost:11434/api/version` whatever `[models]` says (`jobs_doctor.py:26`, `232-249`).
- Nothing validates `[models]` until the first model call. A mistake shows up as an `llm` error, or as a T3 question (because `call_tier` fails closed), or not at all: when the owner adds a `[models]` table for chat with a `default` route and no `embed` route, `knowledge` embeds through `default`, fails, and falls back to keyword search silently. A route-less table and a port out of range also load without complaint.

Suggested fix: one doctor check that loads `[models]`, reports the first error, lists task to endpoint, warns when `knowledge` is installed and `embed` falls to a `default` endpoint without `embed_model`, and pings each local endpoint.

### F10. Minor hardening (P3)

1. `bytes_out` counts UTF-8 content, not the request body. For Vietnamese text the body is about 50 % larger because JSON escapes non-ASCII (probe: 2 800 against 4 303 bytes). Either send `ensure_ascii=False` and count the body, or document the field as "content bytes".
2. The 120 s timeout is per socket operation, so a slow endpoint can hold a call much longer. A total deadline would bound it.
3. An error body from the endpoint is returned in `details["body"]` (500 characters) and flows keep error details in the run file. Some APIs echo part of the request in an error, so "never contains the request" (spec section 3) cannot be guaranteed. Drop the body for cloud endpoints or keep only a status text.
4. `context_for` gives the callee the caller's permissions but takes `cloud_ai` from the callee's manifest (`runtime.py:81-89`, `188-200`). A plugin without `cloud_ai` that calls `llm` in process gets a cloud-capable router. The T3 gate still applies; note it as an invariant or take the stricter of the two.
5. `knowledge` with an `ollama_url` that has a query or fragment raises a pydantic `ValidationError` instead of `invalid_input` (`knowledge/tool.py:83`).
6. `classify` labels and `extract` field descriptions are placed before the delimiter, in the instruction part of the prompt (`tool.py:88-91`, `111-113`). In a flow they can come from an earlier step. The result is still validated by code; limit them to one line without the delimiter.
7. `KnowledgeTool._models` builds its own `ModelRouter` from plugin settings (`knowledge/tool.py:83-92`). It is loopback-checked and local-only, and spec section 8 asked for the settings to keep working, but it is the one place where a plugin constructs a router. A core helper for "local endpoint from a loopback URL" would keep that in `lfmap-core`.

### F11. Spec and architecture drift (P3, read)

- Spec status line still says "Docs only; code comes in a later PR".
- Spec section 10: the folder `docs/specs/model-client-tests/` was never created; tests were written directly in the packages, some under other names. `test_embed_equivalence_bench` does not exist (the run lives in `spikes/mc4-embed-equivalence`).
- Spec section 3 does not mention the 200 000-character limit on `embed`, which is what F1 trips over.
- Spec section 4 rule 6 says a cloud `embed` route is refused at load; a `default` route to cloud is refused only at call time.
- Spec section 8 and `docs/specs/knowledge.md` say `ollama_ok`; the field is `ollama_available`.
- `ARCHITECTURE.md` line 64: "embeddings never go to cloud" (F4) and "a person at a TTY or a preapproved entry" (F2).
- The two data vocabularies are consistent (`DATA_LEVELS` equals `EgressLevel` of ADR-025); the call label of DC-5 (#236) is not in the router yet, as planned.

## 4. Suggested order

1. F1 now (small, local, one PR).
2. F6 smoke on pc-01, then F5 with what the smoke shows.
3. F3, F4, F7 and the F2 decision as preconditions of DC-6 (#237); they can ride with DC-5 (#236), which already changes `models_router.py`.
4. F8 to F11 when convenient; F11 with whichever PR next edits the spec.

No ADR change is proposed. F2 and F4 each need a short owner decision when the first cloud route is planned.
