# Module Spec: Workspace chat UI (Tauri, in-house)

- Status: draft 2026-11-06, written before any code. Plan: RT-05 in [`docs/research/2026-10-23-commercial-replacements.md`](../research/2026-10-23-commercial-replacements.md) (G1, before Tauri starts).
- Roadmap: Phase 2 "Tauri Workspace: chat, danh sách plugin, agent console, phê duyệt hành động".
- Decisions it rests on: ADR-021 (build the chat in-house, clean room for Open WebUI), ADR-003 (REST only when a client needs it), ADR-017/018/023 (tiers, approvals queue, who may approve), ADR-013 (embedded storage), ADR-024 (orchestration stays plain Python).
- Replaces: Open WebUI (internal use only today, ADR-007). ADR-007 stays valid until this ships.

## 1. Purpose and scope

A desktop window on one Windows machine where the owner talks to a local model, sees which LFMAP tools it called and with what result, cites sources from the knowledge index, and handles pending approvals. The minimum that makes Open WebUI unnecessary for LFMAP work, nothing more.

Non-goals: multi-user accounts, cloud sync, model management (pull/delete), RAG settings pages, plugin marketplace (Phase 3), a flow editor (Flows are TOML first, [`flows.md`](flows.md)), voice, mobile, image generation.

## 2. Architecture

```text
Tauri window (webview: React + TypeScript)
   │  invoke / events (Tauri commands, no network exposure)
Rust shell (Tauri)  ── starts and stops ──►  Python sidecar: `lfmap serve rest` (127.0.0.1, bearer token)
                                   └─ talks to ──►  Ollama (OpenAI-compatible /v1/chat/completions, loopback)
```

- The webview never holds the REST token and never talks to a socket itself: it calls Tauri commands; the Rust shell reads the token file (`%LOCALAPPDATA%\lfmap\rest_token`) and forwards. This keeps the REST adapter's rules (R3 token, Host/Origin checks, no CORS) unchanged, and avoids the `[rest] allowed_origins` option listed as open question 3 in [`rest.md`](rest.md) section 9.
- The chat loop (prompt, model call, tool-call round trips, citations) is **Python in `lfmap-core`** (small module `chat.py`, standard library + pydantic), exposed as one REST route family; the UI is a thin client. Reason: the same loop then works from the CLI and tests, and permission checks stay in one language (CLAUDE.md: business logic in Python, adapters generic).
- Model endpoint: any OpenAI-compatible URL from `config.toml`; default Ollama on loopback. A cloud endpoint is refused unless the plugin or call declares `cloud_ai` and the owner allows it (ADR-018 (4), Blueprint 4.4).

## 3. Screens (minimum list)

| # | Screen | Shows | Needs from the API |
| --- | --- | --- | --- |
| S1 | Chat | conversation list, message stream, model picker (configured models only), stop button | `POST /chat` (stream), conversations stored locally |
| S2 | Tool call card (inside S1) | tool name, tier, input, result or error code, time; collapsed by default | tool-call events in the stream |
| S3 | Sources | citations under an answer: file, chunk, score; click opens the file in the default app | `knowledge.search` / `get_context` results already carry them |
| S4 | Plugins | list of installed plugins, operations, tier, adapters on/off | `GET /plugins` (new, read-only registry view) |
| S5 | Approvals | pending proposals (job or flow, plugin.operation, resolved input, tier, expiry), approve and reject | see section 6 |
| S6 | Settings | model endpoint, allowed folders (read-only view of grants), audit log tail | read-only in this phase |

Agent console and run history (Flows runs, jobs) come after S1–S6 and reuse S2/S5 components.

## 4. What the chat may do

- A tool call from the model goes through the **same gate as any REST call**: channel `chat` (new value, decided like `rest`), T0 runs, T1 runs and is audited, T2/T3 are refused with `permission_denied` and shown as a pending approval in S5 (a proposal, never an in-chat "approve" button the model could trigger).
- The model never sees the REST token, file contents it was not given by a tool, or other conversations.
- Conversation storage: SQLite file `chat.db` in the app folder (stdlib `sqlite3`), text only, deletable per conversation; no cloud copy. Prompts that contained `secret`-level knowledge hits are stored as references, as the egress log already does.

## 5. Library choice (all permissive, check before use; none added by this spec)

| Need | Choice | Licence (to verify) | Why |
| --- | --- | --- | --- |
| Shell | Tauri 2 | MIT / Apache-2.0 | already named in Blueprint and Roadmap |
| UI framework | React + TypeScript + Vite | MIT | Blueprint says Tauri + React |
| Chat components | **derive** from LibreChat (MIT) and assistant-ui (MIT, "cần xác minh" in the plan) only for message list, streaming and composer; copy selectively with the MIT notice kept | MIT | ADR-021 order: build, then derive from permissive code, then adopt |
| Base widgets | shadcn/ui (copied components, MIT) or plain CSS | MIT | no runtime package when copied |
| Markdown rendering | a small MIT library or the browser's own `DOMParser` after our own escaping | MIT | untrusted model text must never run scripts or load remote images |

Open WebUI: behaviour and UX only, no code read or copied (BSD-3 plus branding clause). Every copied file gets a `docs/PROVENANCE.md` row and a THIRD_PARTY_NOTICES line (RT-10).
Node dependency count is the new risk: lockfile committed, `npm audit` in CI, no postinstall scripts allowed (`ignore-scripts=true`), versions pinned. The dependency-share script (RT-11) gets a "frontend" line.

## 6. Approvals from the UI: an open decision

ADR-017/018 say approval happens in an interactive terminal ("lfmap approvals approve|reject" refuses a non-TTY), and ADR-023 makes that boundary the person at the console, not a flag. A button in a window is a **different human channel**. Options:

- **A (recommended for the first version):** S5 is read-only: it lists proposals and shows the exact command to paste into a terminal. No ADR change, no new attack surface.
- **B:** S5 can approve. Needs a new ADR: how the window proves a person clicked (OS dialog from the Rust shell, not from the webview; token separate from the REST token; audit channel `ui`). Justified only once A has been used and found annoying.

Hùng decides; A is assumed in the task list.

## 7. Security

- Loopback only; the sidecar binds `127.0.0.1`, no `--host` option exists (REST spec).
- Webview: no remote content, strict Content-Security-Policy (`default-src 'self'`), no `eval`, Tauri allowlist limited to the commands this spec names (read token, start/stop sidecar, open a file the knowledge index returned).
- Opening a file from S3 passes the path through `PermissionManager.require_read` first (CLAUDE.md security rule); UNC and device paths are refused before any I/O.
- Model output is rendered as text/Markdown, never as HTML; links are shown, not auto-opened; tool results are escaped with the same rule as `approvals.visible`.

## 8. Dependencies this spec needs first

1. REST adapter built (implementation deferred in [`rest.md`](rest.md); this is the client that triggers it, ADR-003).
2. `GET /plugins` and the chat route family (new, small).
3. Channel `chat` in `tool.py`/`approval.py`.
4. For approvals S5: nothing new under option A.

## 9. Proposed tasks (after the Flows handoff, before any Tauri code)

| Task | Work | Env |
| --- | --- | --- |
| CU-1 | REST adapter (existing prepared tests), `GET /plugins`, channel `chat`, `chat.py` loop with a fake model, tests | Cloud, Sonnet, `/security-review` |
| CU-2 | Tauri skeleton: sidecar start/stop, token forwarding, S1 with streaming, CSP and allowlist, `npm audit` in CI | Cloud (code) + Local (run) |
| CU-3 | S2, S3, S4, S5 (read-only), conversation store | Cloud |
| CU-4 | Windows smoke: install, chat with `qwen3.8:27b` or the Working model, a T1 tool call, a T2 proposal visible in S5 | Local DIEP-ANH |

## 10. Open points

1. Approvals from the UI: A or B (section 6). Needs Hùng.
2. Python sidecar packaging (PyInstaller was rejected for lfmap-core so far; the first build may require `uv` on PATH). Decide in CU-2.
3. Whether the chat loop streams tool calls from Ollama's native tool API or through MCP; check on DIEP-ANH with the current models in CU-1.
4. Frontend licence check of each chosen package against the Register (new "Software, frontend" rows) before CU-2 merges.

## 11. Definition of Done for this spec (RT-05)

Screen list (section 3), API used (sections 2, 8), derived sources and licences (section 5), the open approval decision (section 6). Code starts only after Hùng answers section 10 point 1.
