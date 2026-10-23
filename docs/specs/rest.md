# Module Spec: REST adapter (Roadmap 1.3)

Version 0.1 · 2026-10-23 · Status: design ready, **implementation deferred to the start of Phase 2**, when n8n or the Tauri UI needs REST (ADR-003; Hùng decided 2026-10-23). Handoff: `docs/handoff/2026-10-23-rest-adapter.md`. Prepared tests: `docs/handoff/prep/2026-10-23-rest/`.

## 1. Purpose

A third generated adapter in `lfmap-core`, next to the CLI and MCP adapters: every operation of a plugin whose manifest sets `[adapters] rest = true` becomes `POST /tools/<plugin>/<operation>` on a local HTTP server started with `lfmap serve rest --port 8765` (Plugin Contract §5). Clients in view: the Tauri UI (Phase 2) and n8n for personal automation (ADR-005, Proposed). Roadmap 1.3 result: "OpenAPI at `/docs`".

The adapter contains no plugin-specific code. Business logic, permissions and approval stay where they are (`Tool`, `PermissionManager`, `Gate`).

## 2. Decisions

| # | Decision | Rejected options |
|---|---|---|
| R1 | **FastAPI** for routing, request validation and OpenAPI; **Uvicorn** as the server. FastAPI is the only new package: Starlette 1.8.0 and Uvicorn 0.54.0 are already in `uv.lock` through `mcp==2.3.0`, annotated-doc through Typer. Regular dependency of `lfmap-core` (not an extra), imported lazily by `serve rest`. Matches Blueprint §2, Plugin Contract §5 and the License Register. | stdlib `http.server` (no new package, proven in MarkitdownTool, but we would hand-write routing, body validation, error mapping and OpenAPI: more own code to maintain than one MIT package). Plain Starlette (no new package, but OpenAPI and validation by hand, and the Plugin Contract names FastAPI). See §8. |
| R2 | Bind **127.0.0.1 only**. No `--host` option. | `--host` with a token requirement (MarkitdownTool does this): opens the API to the LAN for a client we do not have yet. |
| R3 | **Bearer token on every `/tools/` request**, compared with `hmac.compare_digest`. Generated on first `serve rest` (`secrets.token_urlsafe(32)`) into `%LOCALAPPDATA%\lfmap\rest_token`, created with mode 0600 (on Windows the per-user profile ACL protects it). Rotate by deleting the file and restarting. The server prints the file path, never the token. | No token on loopback (any local process or browser page could call it); token in `config.toml` (the user shares that file more readily); env-var token (leaks into process listings and job logs). |
| R4 | Request checks, in this order, before any plugin code runs: (1) **Host header** must be loopback (`127.0.0.0/8`, `::1`, `localhost`, any port) on every path, against DNS rebinding; (2) requests carrying an **`Origin`** header are refused (browsers send it; our clients do not); (3) on `/tools/`: bearer token, before routing, so an unauthenticated caller cannot probe which operations exist; (4) on `POST /tools/`: `Content-Type: application/json` (parameters allowed), `Content-Length` present and at most **1 MiB**. No CORS headers are ever sent. | CORS allow-list now (needed only for a browser UI; Tauri decides this in Phase 2, see §9). Chunked bodies (no client needs them; a length limit is simpler). |
| R5 | Approval: channel `"rest"`, the same `Gate` and `call_tier` as MCP, with **no asker** (HTTP has no back channel to a person). T0 runs. T1 runs and is audited. **T2 is refused** unless `serve rest --approve <plugin>.<op>` (8 h, like MCP) or a grant from `lfmap approvals grant` covers it. **T3 is refused** unless a time-limited grant made in an interactive terminal or a preapproved destination covers it; `--approve` never covers `external` operations. This is ADR-017 (2) applied as written; no ADR change. | Elicitation-like confirmation over HTTP (the caller is a program and would answer itself); refusing T1 on REST (T1 only creates new files in declared roots and is audited, the same as MCP). |
| R6 | Errors: every response that is not 200 has the body `{code, message, details}` (Plugin Contract §6). Status: `invalid_input` 400, `permission_denied` 403, `not_found` 404, `backend_unavailable` 503, `timeout` 504, `internal` 500. Request-level failures reuse the standard codes: missing/bad token 401 `permission_denied` + `WWW-Authenticate: Bearer`; bad Host or Origin 403 `permission_denied` (`details.reason` = `host` / `origin`); wrong media type 415, missing length 411, too large 413, wrong method 405 (all `invalid_input`); unknown route 404 `not_found`. Unexpected exceptions: 500 `internal` with empty `details`; the traceback goes to stderr only. | FastAPI's default 422 shape (a second error format for clients); new error codes (the contract fixes the list). |
| R7 | `/health` (GET, no token), `/openapi.json` (GET, no token) and `/docs` (GET, no token) are Host/Origin-checked but open: they reveal plugin ids, operation names and schemas, not data. `/docs` is a **self-contained HTML page** generated from the OpenAPI document: no JavaScript, no external assets, `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'`. FastAPI's Swagger UI and ReDoc are switched off. | FastAPI's Swagger UI (loads JS from a CDN into a page where the user pastes the token: supply-chain risk and network egress); bundling swagger-ui-dist (one more asset set to update); token-protected docs (a browser cannot send the header). |
| R8 | Plugins: the adapter serves only manifests with `rest = true`. Default stays `false` (Plugin Contract §2). In the implementation PR only `echo` turns it on (smoke test). A real plugin turns it on in its own small PR when a client needs it (ADR-003). `powershell` stays `false` until a separate review. | Turn on every plugin (exposes T3 `powershell.run` and private knowledge search to every local token holder for no client). |
| R9 | Sync operations run in FastAPI's worker thread pool, like MCP tools run in a worker thread. Plugin stdout is not redirected (HTTP does not use stdout). No request timeout in the adapter; operations keep their own (`timeout` code). | Async plugins (contract is sync); a per-request timeout (would kill work mid-write). |

## 3. Command

```powershell
lfmap serve rest [--port 8765] [--plugins echo --plugins knowledge] [--approve knowledge.reindex]
```

- `--port`: 1024..65535, default 8765. Always on 127.0.0.1.
- `--plugins`: plugin ids, default all (only those with `rest = true` get routes).
- `--approve`: like `serve mcp --approve` (up to T2, 8 hours, never `external`; unknown names are an error at start).
- Prints `lfmap rest: http://127.0.0.1:<port>/docs, token in <path>` to stderr. Uvicorn log level `warning`; the access log never contains bodies or headers.

## 4. HTTP surface

| Method + path | Token | Body | 200 response |
|---|---|---|---|
| `GET /health` | no | – | `{"ok": true, "version": "<lfmap-core>"}` |
| `GET /openapi.json` | no | – | OpenAPI 3.1, one path per operation, `components.securitySchemes.bearer = {type: http, scheme: bearer}`, `security: [{bearer: []}]` on every `/tools/` operation, description ends with `Side effects: <x> (tier <Tn>).` |
| `GET /docs` | no | – | HTML (R7) |
| `POST /tools/<plugin>/<operation>` | yes | the operation's input model as a JSON object | the output model, `model_dump(mode="json")` |

Example:

```powershell
$token = Get-Content "$env:LOCALAPPDATA\lfmap\rest_token"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/tools/echo/say `
  -Headers @{ Authorization = "Bearer $token" } -ContentType application/json -Body '{"text": "xin chao"}'
```

## 5. Module layout

`packages/lfmap-core/src/lfmap_core/rest_adapter.py`, mirroring `mcp_adapter.py`:

| Name | Role |
|---|---|
| `route(plugin_id, operation) -> str` | `/tools/<plugin>/<operation>` (plugin id unchanged, ADR-014). |
| `token_path() -> Path`, `load_or_create_token(path=None) -> str` | R3. |
| `build_app(registry, plugin_ids, token, approve=()) -> FastAPI` | Checks `approve` like MCP, one route per served operation, middleware for R4, exception handlers for R6, OpenAPI post-processing and `/docs` for R7. Empty token raises `ToolError`. |
| `serve(registry, plugin_ids, port=8765, approve=()) -> None` | Token, `build_app`, `uvicorn.run(app, host="127.0.0.1", port=port)`. |

`cli.py` gets `serve rest` next to `serve mcp`. Each route's endpoint takes the input model as the JSON body (FastAPI validates it), then: `Gate(plugin, op, "rest", Policy.from_config(load_config()), preapproved(), None)`, `gate(call_tier(...), "side_effects")`, `run_operation(..., channel="rest", approver=gate)`. `_check_approvals` and the 8-hour TTL may be shared with `mcp_adapter.py` (move to `approval.py`) if that stays small.

## 6. Security notes

- Path security is unchanged: payload paths reach the plugin, which calls `require_read` / `require_write`; `build_tool` takes variables from `config.toml`, never from the request.
- Channel `rest` is already an egress channel in `lfmap-knowledge`: secret roots are hidden and every hit is written to `egress_log`, exactly as for MCP.
- The token is a capability for every served operation up to T1 and every `--approve`d T2. Any process running as the user can read the file; this is the same trust boundary as `config.toml` and the MCP client config.
- A browser page cannot call the API: it cannot set `Authorization` without a CORS preflight we never answer, it always sends `Origin` on cross-origin POST, and DNS rebinding fails the Host check.

## 7. Tests (prepared)

`docs/handoff/prep/2026-10-23-rest/test_rest_adapter.py`, 41 test functions (52 cases), copied to `packages/lfmap-core/tests/`. They use Starlette's `TestClient` against `build_app` (no socket) and cover: routing and output, channel `rest`, error mapping and body shape, schema errors, non-object and malformed JSON, 404/405, `rest = false` plugins hidden, `--plugins` filter, 500 without details; token required and checked before routing; Host and Origin checks; no CORS; content type, charset, size limit; T0 not audited, T1 audited, T2 denied / `--approve` / grant / expiry, T3 denied even with `--approve` / allowed with grant, `external` cannot be pre-approved, policy `deny`; `/health`, OpenAPI paths/schemas/bearer, self-contained `/docs`; token file creation, permissions and rotation; `serve rest` binds 127.0.0.1 with `--port` and has no `--host`. A throwaway reference implementation (not in the repo) passes all 52 cases and the full suite on Linux.

## 8. Options compared

| | FastAPI + Uvicorn (chosen) | Starlette + Uvicorn | stdlib `http.server` |
|---|---|---|---|
| New packages | 1 (`fastapi`, MIT) | 0 | 0 |
| Own code | ~250 lines (reference implementation) | ~300, estimate (OpenAPI + validation by hand) | ~350, estimate (plus threading, body parsing) |
| OpenAPI | generated from the Pydantic models | hand-built from `model_json_schema()` | hand-built |
| Fits docs | Blueprint, Plugin Contract §5, License Register already name FastAPI | contract text needs an edit | contract text needs an edit |
| Risk | FastAPI 0.x minors sometimes break; mitigated by `uv.lock` and the prepared tests | Starlette's API is stable since 1.0 | none from deps; more of our own HTTP edge cases |

## 9. Open questions

1. ~~When to build~~ Decided 2026-10-23: at the start of Phase 2, when n8n or the Tauri UI needs REST (ADR-003 unchanged).
2. **n8n in Docker** cannot reach 127.0.0.1 on the host (it calls `host.docker.internal`, which is not loopback). Options when n8n arrives: run n8n natively (`npx n8n`) on loopback, or an ADR for a LAN/docker bind with a stricter token. Not solved here.
3. **Tauri UI**: its webview sends an `Origin` (e.g. `tauri://localhost` / `http://tauri.localhost`). Phase 2 adds `[rest] allowed_origins` in `config.toml` (exact match, plus CORS for those origins only), or the UI calls the SDK in-process through a Python sidecar and needs no REST at all.
4. Should REST calls get their own audit field (client name)? Not needed while there is one token.
