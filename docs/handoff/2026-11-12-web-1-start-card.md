# Handoff addendum: start card for WEB-1 (#269)

Issue: [#269](https://github.com/hungnp1999/lfmap/issues/269). Spec: [docs/specs/web-plugin.md](../specs/web-plugin.md) (sections 2 to 11, 13, 14, 16). Parent: #218 group G1, part of #191. Handoff of the spec: [2026-11-11-web-plugin-spec-g1.md](2026-11-11-web-plugin-spec-g1.md).

## State on main (2026-11-12)

- Spec merged (PR #255) with the owner decisions of 2026-11-12 in section 16 (PR #266): T0 kept and T3 for a URL query longer than 200 characters; no `http`; `save` defaults to `false`; three WEB-1 fixes (below).
- DC-2 (`data_guard.py`) is merged. WEB-1 does not touch the approval gate; `web.fetch` sends no `data` argument, so no class applies.
- Executor: Claude Code, Cloud. Model: **Opus proposed** (new network boundary, same reasoning as DC-2); the owner decides. One draft PR, `Refs #218` and `Closes #269`. WEB-2 (plugin) starts only after this PR is merged.

## What WEB-1 covers, and what moved to WEB-2

| In WEB-1 (core) | In WEB-2 (plugin) |
| --- | --- |
| `web.py`, `web_http.py`, `web_rate.py`, `web_egress.py`; `Adapters.web`; `ctx.web`; fixture certificate; core tests | `plugins/lfmap-web`, `WebTool.call_tier`, `save` copy to `data_dir`, flow-step and CLI/MCP tests, README, `ARCHITECTURE.md` invariant text |
| The constant `QUERY_T3_LIMIT = 200` and a pure helper in `web.py` that says whether a URL query is longer than the limit | `WebTool.call_tier` calls that helper and returns `"T3"`; the job-channel end-to-end check |

Why the split: `call_tier` is a classmethod of the plugin's `Tool` (`tool.py`), and the plugin does not exist yet. The owner's decision (section 16.1) is met when both halves are merged; WEB-1 proves the bound, WEB-2 proves the gate. Section 16.4(c) names one test, `test_long_query_is_t3`: WEB-1 ships its core part (boundary 200 and 201 on the helper, query only, fragment and path length not counted), WEB-2 adds the same name in the plugin tests (201 characters are T3 on a `job` channel, nothing is sent, 200 stay T0). If the split looks wrong while coding, stop and report.

Spec drift to know about: section 11 says the tests are "copied unchanged" from `docs/specs/web-plugin-tests/`. That folder does not exist. Write the tests directly in `packages/lfmap-core/tests/` with the names below; do not create the folder.

## Required changes from the owner decisions (section 16.4)

1. **DNS under the deadline.** `getaddrinfo` has no timeout. Run it in a worker thread and abandon it when the wall-clock deadline of `timeout_s` passes (a daemon thread; the fetch raises `backend_unavailable`, `reason: timeout`). The same deadline covers DNS, connect, TLS, headers, body and every redirect hop. Test `test_dns_hang_respects_timeout`: a resolver stub that blocks for 10 s with `timeout_s = 1` raises within about 1.5 s; no socket is opened.
2. **Test seam stays out of production.** `resolver`, `ssl_context`, `clock`, `NetworkPolicy(allow_non_global)` and the test-only `port` are keyword-only constructor arguments of `WebFetcher`. Nothing in `config.toml`, a manifest or a plugin may set them, and `ctx.web` exposes only `fetch`. Test `test_runtime_fetcher_refuses_loopback`: build the fetcher the way `runtime.py` does (`_attach_web`, defaults only) against the fake server on `127.0.0.1` and show `blocked_address`; inspect that `ctx.web` has no attribute that reaches the policy, the resolver or the port.
3. **`test_long_query_is_t3`** (core part, as above).

## Frozen tests (write first, hand-written expectations)

From spec section 11, in `packages/lfmap-core/tests/`: `test_host_not_in_allowlist_refused`, `test_redirect_outside_allowlist_refused`, `test_private_ip_refused_after_dns`, `test_no_cookies_no_proxy`, `test_size_limit_truncates_or_refuses`, `test_rate_limit_per_host`, `test_audit_line_host_bytes_in`, `test_no_config_denies_all`, `test_non_text_content_type_refused`, `test_url_userinfo_refused`, `test_tls_certificate_verified`, `test_timeout_is_wall_clock`, `test_redirect_within_allowlist_followed`, `test_per_run_call_cap`, `test_config_validation`, `test_untrusted_page_text_is_data`. Plus `test_dns_hang_respects_timeout`, `test_runtime_fetcher_refuses_loopback`, `test_long_query_is_t3` (core part).

Left to WEB-2: `test_save_copy_to_data_dir`, `test_web_plugin_manifest_permissions`, `test_call_tier_is_t0_unattended`, `test_flow_step_fetch_then_convert`, `test_cli_and_mcp_generated`, and the plugin side of `test_no_config_denies_all` (`ctx.web` without `[adapters] web = true`, which can already be tested in core with a fake manifest: do it in WEB-1).

Harness (spec section 11): fake HTTPS server thread (`http.server` + `ssl`) on `127.0.0.1:<random>`; a committed self-signed certificate valid for `fake.test`, `other.test` and `blocked.test` (SANs; generate with the `openssl` command line once, 100 years, no private data, commit key and certificate under `tests/fixtures/web/` and say how it was made in a short `README` there); resolver stub; a **socket guard** fixture that fails the test on any `connect` or `getaddrinfo` outside the allowed loopback address and port and counts calls. All offline. Hand-write expected values (for example the blocked address list); do not derive them with the code under test.

## File scope

May change or create: `packages/lfmap-core/src/lfmap_core/{web.py, web_http.py, web_rate.py, web_egress.py, manifest.py, tool.py, runtime.py}`, `packages/lfmap-core/tests/{test_web_config.py, test_web_fetch.py, test_web_rate.py, test_web_audit.py}` and `tests/fixtures/web/`, `ARCHITECTURE.md` (module map only, add the four modules and `web_rate.db`), `changelog.d/218-web-core.added.md`.

Must not touch: `approval.py`, `permissions.py`, `cli.py`, `mcp_adapter.py`, `config.py`, any adapter, `plugins/`, `docs/specs/*`, ADR files. If a file outside this list is needed, stop and report. `approval.py` already allows the audit fields `event`, `status`, `host`, `bytes_out`, `bytes_in`; if one is missing, stop and report.

## Rules that must not regress

- The order of checks of spec section 5; no socket before step 7; every redirect hop restarts at step 3. The first failing check ends the call.
- URL validation and the allow-list comparison are written **inline in the function that opens the connection, on the same variable** (CLAUDE.md: CodeQL does not follow checks hidden in helpers). `check_url` may exist for the early refusals, but the connecting function repeats the host comparison inline.
- Connect to the address that was checked, never to the name; `ssl.create_default_context()` with `server_hostname` = the allowed host; verification never disabled; TLS 1.2 or higher.
- Proxy variables ignored (own `http.client` socket, no opener, no cookie jar); `Accept-Encoding: identity`; only GET; the fixed headers of spec section 4 and no others.
- Body read stops at the cap; content type checked before the body is read; text types only.
- Rate state in `web_rate.db` (`BEGIN IMMEDIATE`), never sleeps, fails closed with `reason: rate_state` when the file cannot be opened. The per-run cap is in memory per fetcher.
- Audit: a `sent` line before the socket opens (if that write fails, nothing is sent), then the result line; no URL, no content, no addresses, no cookies. A malformed URL writes no line; a refusal before a socket writes one line with the reason as `status`.
- Errors are `ToolError` only, with the codes and `reason` values of spec section 10; messages never carry the query, headers or more than 500 characters of body.
- Standard library only. No new dependency.

## Start prompt (paste into a new Claude Code Cloud session, repo lfmap, model as the owner chooses)

```
Task WEB-1 of lfmap #218 / issue #269 (core of web.fetch: ctx.web, [web] config, fetcher, rate state, audit). Read docs/handoff/2026-11-12-web-1-start-card.md and docs/specs/web-plugin.md (sections 2 to 11, 13, 14, 16). Branch from up-to-date main; merge origin/main again before push. Do not write the plugin (WEB-2).

File scope: exactly the list in the start card. If you need a file outside it, or approval.py lacks an audit field, stop and report.

Write the tests first with exactly the names in the card (offline: fake HTTPS server on loopback, committed certificate for fake.test/other.test/blocked.test, resolver stub, socket guard). Hand-write expected values. Then implement web.py, web_http.py, web_rate.py, web_egress.py, Adapters.web, ctx.web and the runtime attach. Three owner-decided requirements: (1) DNS resolution runs under the same wall-clock timeout_s deadline as the rest of the fetch (worker thread abandoned at the deadline), test_dns_hang_respects_timeout; (2) resolver, ssl context, clock, NetworkPolicy and the test port are keyword-only constructor arguments unreachable from config, manifest or plugin, test_runtime_fetcher_refuses_loopback; (3) QUERY_T3_LIMIT = 200 in web.py with a pure helper and the core part of test_long_query_is_t3 (200 stays T0, 201 is T3; the plugin wiring is WEB-2).

Rules: spec section 5 order of checks, inline URL and allow-list checks in the connecting function on the same variable, connect to the checked address, verification on, proxy variables ignored, no cookies, identity encoding, read stops at the cap, fail closed on rate state, audit host and bytes only, ToolError codes of section 10, standard library only.

Run uv run pytest, uv run ruff check . and uv run ruff format --check . (7 test_jobs_doctor failures on Linux are pre-existing). Existing suites pass unedited. Update ARCHITECTURE.md module map only. Commit trailers: Dev-Environment: cloud and Claude-Session (add Dev-Environment by hand if the hook did not). Draft PR from the template with "Refs #218" and "Closes #269". Then run /security-review on the diff and answer every finding in the PR, including the three confirmations of the card review checklist. Do not merge; report the PR link.
```

## Review checklist for the thread (after the PR)

- Only files of the scope list changed; no new dependency; old suites unedited and green; CodeQL green.
- All frozen tests exist with those names; socket guard asserts "no socket" for every refusal before step 7.
- Section 5 order holds; the inline allow-list check sits in the connecting function; connect uses the validated IP; rebinding test present.
- `allow_non_global`, `port`, resolver and ssl context cannot be set from config, manifest, plugin or `ctx.web` (read the constructor and `runtime.py` by eye, not only the test).
- DNS is under the deadline (`test_dns_hang_respects_timeout`); `QUERY_T3_LIMIT = 200` tested at 200 and 201.
- Audit lines: `sent` then result, no URL path or query in the file; failed first write sends nothing.
- `/security-review` run and every finding answered; `ARCHITECTURE.md` module map updated (invariant wording waits for WEB-2).
- Verdict: Approve / Approve with changes / Reject. Merge squash only when the PR is not draft.
