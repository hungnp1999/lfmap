# Handoff addendum: start card for WEB-2 (plugin `lfmap-web`, #218 G1)

Issue: WEB-2 [#271](https://github.com/hungnp1999/lfmap/issues/271) (blocked by [#269](https://github.com/hungnp1999/lfmap/issues/269)). Spec: [docs/specs/web-plugin.md](../specs/web-plugin.md), sections 2, 4, 7, 9, 10, 11, 14 and 16 (owner decisions of 2026-11-12). Parent: #218 (do not close it), part of #191. Handoff: [2026-11-11-web-plugin-spec-g1.md](2026-11-11-web-plugin-spec-g1.md). Card format follows [2026-11-11-dc4-start-card.md](2026-11-11-dc4-start-card.md).

## Start condition

WEB-1 ([#269](https://github.com/hungnp1999/lfmap/issues/269), PR #277) is merged: `web.py`, `web_http.py`, `web_rate.py`, `web_egress.py`, `Adapters.web` and `ctx.web` are on `main`. This task is unblocked. If `git grep -n "def web" packages/lfmap-core/src/lfmap_core/tool.py` finds nothing on your checkout, you are on a stale base: update, else stop and report. Environment: Cloud, Claude Code, **Sonnet**. One PR, draft, `Closes #271` and `Refs #218`.

## Session protocol (standing rule of the owner, 2026-11-13)

1. Open the **draft PR at your first commit** (title `feat(web): plugin lfmap-web (WEB-2)`, body from the PR template, `Closes #271`, `Refs #218`), so the reviewing thread can subscribe to it from the start. Keep it a draft until CI is green.
2. Post your **final report as a PR comment whose first line is `DONE`**, followed by: what changed, test results (including the Linux baseline failures), `/security-review` findings and your answers, open questions. Post it only when the work is complete and CI on the head commit is green or you state exactly why it is not. Do not post `DONE` earlier.
3. Do not merge. The reviewing thread starts the review when it sees `DONE` with green CI.

## Carry-overs from the WEB-1 review ([#271 comment](https://github.com/hungnp1999/lfmap/issues/271#issuecomment-6842397431))

- `ctx.web_fetcher` is a public field of `ToolContext` (same as `model_router`), so in-process plugin code could replace it with its own `WebFetcher`. Plugins can already open sockets; this is not a sandbox. Record it as a **residual risk** in the `ARCHITECTURE.md` invariant text.
- A failed `sent` audit write raises `backend_unavailable` with `reason: audit_failed`, which is missing from the error table of `docs/specs/web-plugin.md` section 10. Add the row (docs only; this is the one spec edit allowed).
- `WebTool.call_tier` uses `web.long_query` from core (the bound and the core test exist); the plugin part of `test_long_query_is_t3` is owed here.

## Goal

A thin plugin `plugins/lfmap-web` with one operation `web.fetch`. All network rules live in the core fetcher; the plugin only validates input, calls `ctx.web`, decides the tier, optionally saves a copy to its own `data_dir`, and is registered in the workspace. Then `lfmap web fetch URL`, MCP `web_fetch` and the flow step `call = "web.fetch"` exist with no adapter change.

## Decisions already taken (do not reopen)

From spec section 16 (owner, 2026-11-12):

1. Tier is T0, but `WebTool.call_tier` returns `"T3"` when the URL has a query string longer than 200 characters (200 stays T0, 201 is T3). Use `web.long_query` from `web.py` (do not define a second bound). A T3 call is queued or refused on `job`, `event` and `flow`, so a long query never runs unattended.
2. The ADR exception text is accepted but the ADR file is **not** edited here (separate gate:po step). The `ARCHITECTURE.md` invariant text of spec section 7 is applied in this PR.
3. No `http`; `save` defaults to `false`.

Reversible choices taken here so the session does not stall:

- `call_tier` parses the URL with the same helper WEB-1 uses (`check_url` or what it exposes); an unparsable URL returns `None` (base tier) and the operation then fails in the fetcher with `invalid_input`. Do not duplicate URL parsing in the plugin.
- The saved-copy file name is built from the UTC time, the validated host and the first 8 hex characters of the body SHA-256, exactly as spec section 4. Create `data_dir/pages/` with the plugin's `ctx.data_dir`; do not take any path from the input.
- `FetchOutput` fields are exactly those of spec section 4; `saved_path` is the string path or `null`.

## File scope (required)

May create:

- `plugins/lfmap-web/pyproject.toml`, `README.md`
- `plugins/lfmap-web/src/lfmap_web/{__init__.py, lfmap.toml, schemas.py, tool.py}`
- `plugins/lfmap-web/tests/{conftest.py, test_tool.py}` (reuse WEB-1's fake HTTPS server fixture and socket guard; import or copy, do not weaken them)
- `changelog.d/218-web-plugin.added.md`

May edit:

- `ARCHITECTURE.md`: replace the "No network beyond loopback ..." invariant with the text of spec section 7, and add `web.py`, `web_http.py`, `web_rate.py`, `web_egress.py`, `web_rate.db` to the module map unless WEB-1 already did (check first)
- root `pyproject.toml` (dependency list and `[tool.uv.sources]` entry for `lfmap-web`) and `uv.lock` (`uv lock`)
- `docs/specs/flows.md` only if an example needs the new step (otherwise leave it)
- `docs/specs/web-plugin.md` section 10 only: add the `audit_failed` row

Must not touch: other sections of `docs/specs/web-plugin.md`, anything under `packages/lfmap-core/src/` (if the plugin seems to need a core change, stop and report to the thread: it belongs to WEB-1 or a new issue), `approval.py`, `permissions.py`, adapters, `config.toml` handling, other plugins, `docs/` ADR files.

## Steps

1. Read the spec sections listed above, `plugins/lfmap-llm` (closest model for a plugin with `network = true`) and `plugins/lfmap-echo`, and the WEB-1 code on `main` (`web.py`, `tool.py` `ctx.web`).
2. Write the frozen tests first (names below), run them, see them fail for the right reason.
3. Manifest `lfmap.toml`: id `web`; `[adapters] cli = true, mcp = true, rest = false, events = false, web = true`; `[permissions] fs_read = [], fs_write = [], network = true, exec = [], cloud_ai = false`; one operation `fetch`, `side_effects = "external"`, `min_tier = "T0"`; `[dependencies.licenses]` as in the other plugins. No second operation.
4. `schemas.py`: `FetchInput` (`url`, `max_bytes`, `save`) and `FetchOutput` as in spec section 4, pydantic with `extra="forbid"`.
5. `tool.py`: `WebTool(Tool)` with `call_tier` (T0, T3 on a long query) and `fetch` calling `ctx.web`; map nothing: fetcher errors are already `ToolError` with the reasons of spec section 10. Implement `save` last. Page text is returned verbatim (spec section 9); never open, parse or follow it.
6. `pyproject.toml` with entry point `web = "lfmap_web.tool:WebTool"`; add the workspace entry and run `uv lock`.
7. README: allowed hosts live in `config.toml` `[web]`, the limits, one example of `lfmap web fetch`, the terms-of-service note (no `robots.txt` check; the owner is responsible for the sites chosen; at most 12 requests a minute per host by default), and that Cloud sessions never fetch real sites.
8. `ARCHITECTURE.md` and the changelog fragment.
9. Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` (7 `test_jobs_doctor` failures on Linux are the known baseline; compare, do not "fix" them).
10. Open the draft PR from the template, then run `/security-review` on the diff and answer every finding in the PR. Do not merge; report the PR link.

## Frozen tests (exact names; spec section 11)

In `plugins/lfmap-web/tests/`: `test_web_plugin_manifest_permissions`, `test_call_tier_is_t0_unattended`, `test_long_query_is_t3`, `test_flow_step_fetch_then_convert`, `test_cli_and_mcp_generated`, `test_save_copy_to_data_dir`, `test_untrusted_page_text_is_data`.

- `test_long_query_is_t3` (owner decision 16.4c): a 200-character query stays T0; 201 is T3; on a `job` channel the 201 case is queued or refused and the fake server saw 0 requests; the audit still shows `bytes_out` for the T0 case.
- All tests are offline: fake HTTPS server on loopback, resolver stub, socket guard (WEB-1 fixtures). No test resolves a real name.
- Hand-write expected values; do not derive them from the code under test. Do not edit any WEB-1 test.

Note on overlap: #269 has a core part of `test_long_query_is_t3` (the constant and bound); this card owns the part that needs `WebTool`. Keep both; do not edit or delete the WEB-1 test.

## Dependencies

Blocked by: none (#269 merged).  WEB-3 (real check on DIEP-ANH, G4) follows this task and is not part of it.

## Resource

none (Cloud, offline).

## Completion criteria

- [ ] The 7 frozen tests pass on CI; WEB-1 tests unchanged and green
- [ ] `lfmap web fetch --help` and the MCP tool `web_fetch` exist with no change under `packages/lfmap-core/src/`
- [ ] With no `[web]` table every URL is refused with `host_not_allowed` (checked through the plugin, not only the fetcher)
- [ ] `ARCHITECTURE.md` invariant and module map updated; changelog fragment present
- [ ] `/security-review` run and every finding answered in the PR
- [ ] `audit_failed` row added to spec section 10; residual risk of `ctx.web_fetcher` recorded in the `ARCHITECTURE.md` invariant
- [ ] Draft PR opened at the first commit; final report posted as a PR comment starting `DONE`
- [ ] CodeQL and tests green; PR is a draft until then

## Start prompt (paste into a new Claude Code Cloud session, model Sonnet, repo lfmap)

```
Task WEB-2 of lfmap #218 (G1): plugin lfmap-web. Read docs/handoff/2026-11-12-web-2-start-card.md first, then docs/specs/web-plugin.md sections 2, 4, 7, 9, 10, 11, 14, 16, plugins/lfmap-llm and plugins/lfmap-echo, and the merged WEB-1 core code (web.py, ctx.web in tool.py). WEB-1 is on main (PR #277); if ctx.web does not exist on your checkout, update, else stop and report. Also read the WEB-1 carry-overs in issue #271 (comment 6842397431). Branch from up-to-date main; merge origin/main again before push.

File scope: plugins/lfmap-web/** (new), changelog.d/218-web-plugin.added.md, ARCHITECTURE.md (invariant + module map), root pyproject.toml and uv.lock. Do not touch packages/lfmap-core/src, approval.py, permissions.py, adapters or other plugins. If you need another file, stop and report.

Write the frozen tests first with exactly these names: test_web_plugin_manifest_permissions, test_call_tier_is_t0_unattended, test_long_query_is_t3, test_flow_step_fetch_then_convert, test_cli_and_mcp_generated, test_save_copy_to_data_dir, test_untrusted_page_text_is_data. Hand-write expected values. Reuse the WEB-1 fake HTTPS server and socket guard; all tests offline.

Rules: one operation fetch, side_effects external, min_tier T0; call_tier returns T3 when the URL query is longer than 200 characters (use WEB-1's constant; 200 stays T0, 201 is T3); no http; save defaults to false and the copy goes to ctx.data_dir/pages with a name made of UTC time, host and sha256[:8] only; page text is returned verbatim and never interpreted; no URL parsing duplicated in the plugin; no network code in the plugin; standard library plus lfmap-core only; do not edit the ADR file.

Run uv run pytest, uv run ruff check . and uv run ruff format --check . (7 test_jobs_doctor failures on Linux are pre-existing). Commit trailers: Dev-Environment: cloud and Claude-Session (the cloud hook may not add Dev-Environment: add it by hand). Open the draft PR at your FIRST commit (template, "Refs #218", "Closes #271"). Then run /security-review on the diff and answer every finding in the PR. When complete and CI is green, post your final report as a PR comment whose first line is exactly DONE (what changed, test results, security-review answers, open questions). Do not post DONE earlier. Do not merge.
```

## Review checklist for the thread (after the PR)

- Only files in the scope list changed; nothing under `packages/lfmap-core/src/`; ADR files untouched.
- Manifest matches spec section 2 exactly (one operation, `network = true`, `cloud_ai = false`, `[adapters] web = true`).
- `call_tier`: T0 normally, T3 at 201 characters of query, using `web.long_query`; no second URL parser.
- Saved-copy name has no URL path or query; the path stays inside `data_dir`; default is no copy.
- The plugin opens no socket and imports no `http.client`, `socket`, `ssl` or `urllib.request`.
- The 7 frozen tests exist with those names and pass; old suites green except the known Linux baseline; CodeQL green.
- Review starts only on a `DONE` comment with green CI on the head commit. `audit_failed` row and `ctx.web_fetcher` residual risk present.
- `/security-review` findings answered. Verdict: Approve / Approve with changes / Reject. Merge squash only when not draft.
