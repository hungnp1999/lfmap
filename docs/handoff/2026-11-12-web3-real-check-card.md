# Handoff addendum: task card for WEB-3 (real check of `web.fetch` on DIEP-ANH)

Issue: [#270](https://github.com/hungnp1999/lfmap/issues/270). Parent handoff: [2026-11-11-web-plugin-spec-g1.md](2026-11-11-web-plugin-spec-g1.md). Spec: [docs/specs/web-plugin.md](../specs/web-plugin.md) (sections 3, 8, 12, 14, 16). Tracking issue: #218 (gap G1, folds into G4; this task never closes it). Scenario: S1 in [acceptance-scenarios.md](../specs/acceptance-scenarios.md). Card format follows [2026-11-11-dc4-start-card.md](2026-11-11-dc4-start-card.md).

## Task card

- Task: WEB-3, real check of `web.fetch` on the two S1 sites. Roadmap: Phase 2, #218 G1 / G4.
- Labels: `exec:CC`, `P1`, `res:Local`, `blocked`.
- Executor: Claude Code session on DIEP-ANH (pc-01) started by the owner. Model: Sonnet. Cloud sessions never fetch the real sites (spec section 12).
- Blocked by: [#269](https://github.com/hungnp1999/lfmap/issues/269) (WEB-1, core fetcher) and [#271](https://github.com/hungnp1999/lfmap/issues/271) (WEB-2, plugin `lfmap-web`), both merged, and `D:\lfmap-runtime` updated from main. Order: WEB-1, then WEB-2, then this.
- Start when: WEB-2 is merged and the owner has one evening slot with internet. Preflight one day before (below).
- Size: about 1 hour at the machine, no GPU.

## Goal

Show, with two real requests, that the merged `web.fetch` reads the tender listing pages of the two S1 sites as usable text, and record what that means for G4 (fetch directly, or look for an export, RSS or API). Output is a report and two saved sample pages, not product code.

## State to verify first (do not assume)

- WEB-1 and WEB-2 are on `main`; `lfmap web fetch --help` works from the runtime root.
- The test `test_flow_step_fetch_then_convert` and `test_cli_and_mcp_generated` exist and pass on CI.
- The fixes of spec section 16.4 are in: `test_dns_hang_respects_timeout`, `test_long_query_is_t3`.

If any of this is missing, stop and comment on the issue; do not patch the fetcher in this task.

## File scope (required)

May create:

- `docs/research/2026-11-xx-web-fetch-real-check.md` (report, English)
- `tests/samples/web/` is NOT used. Saved pages go to the plugin `data_dir/pages/` on pc-01 and, only after the owner agrees, a trimmed copy under `docs/specs/acceptance-samples/s1/` (see step 7).
- `changelog.d/218-web-real-check.added.md`

Must not touch: any file under `packages/`, `plugins/`, `config.toml` of the repo, ADRs. The owner edits the real `config.toml` on pc-01 by hand.

## Steps

1. **Preflight (the day before, owner, 5 minutes).** Open both sites in a browser. Write down the exact host in the address bar of each listing page (with or without `www`), and whether the page shows tender rows without logging in. Paste the two hosts and two listing URLs into the issue. Matching is exact (spec section 3), so a wrong host fails closed.
2. **Config (owner, by hand).** Add the two exact hosts to `[web] allowed_hosts` in the pc-01 `config.toml`. Leave the other keys at default. Do not set anything else.
3. **Dry checks, no internet.** `lfmap config` shows the `[web]` table; `lfmap web fetch https://example.com/` is refused with `host_not_allowed` and appends one `web_fetch` audit line; an `http://` URL is refused with `invalid_input`.
4. **One real request per site**, from the interactive terminal, by hand: `lfmap web fetch <listing URL> --save`. One request each, no loop. If a site answers `http_403` or `http_429`, stop for that site and record it; do not retry or change the `User-Agent` (spec section 13).
5. **Compare with the browser.** For each saved page: is the tender list present in the HTML text, or is the page a shell built by scripts? Record: closing date, field and bidding-form fields visible or not; `truncated`; encoding problems (Vietnamese diacritics, Russian); size in bytes.
6. **Audit check** (spec section 12 step 4). `audit.jsonl` has exactly two `web_fetch` pairs (`sent`, then `ok` or the error reason), the right hosts, `bytes_in` equal to the saved file sizes, and no URL path, query or page text anywhere in the lines.
7. **Offline replay.** With the network off (or the hosts removed from the allow-list), run a one-step flow or a plain `markitdown`/text read over the saved files to show S1 can be tested without the sites. Do not store real tender data in the repo: if a sample is wanted in the repo, strip it to the structure plus three dummy rows, and ask the owner first (public data, but keep the repo small).
8. **Report.** Write the report: hosts used, date, per site `status`, `bytes`, `truncated`, list present yes/no, script-built yes/no, verdict, and the G4 recommendation: (a) fetch directly in the daily job; (b) the site needs an export, RSS or API (name the one seen in the page source or the site menu); (c) a browser would be needed (then stop: that is a new decision, not part of v1). Also record anything that suggests a spec change (header, content type, charset, redirect to another host, rate).
9. Commit the report and fragment, open a draft PR `Refs #218`, no `Closes`.

## Frozen checks

No new code tests. Pass rule, all of:

- [ ] Both sites fetched once each with a recorded `status` (success or a recorded refusal reason)
- [ ] Audit lines match step 6
- [ ] Verdict for each site is one of (a), (b), (c) with the evidence that supports it
- [ ] No cookie, no second request, no change to the allow-list beyond the two hosts

## Stop conditions

Stop and tell the owner (do not work around) if: a request goes to a host other than the two listed; the audit shows a URL or page text; the fetch needs a header, cookie or login; either site asks for a captcha; a result suggests the fetcher should change (file an issue instead).

## Data and egress

Public pages only, `normal` class. What leaves the machine: two HTTPS GETs (URL, fixed headers). Nothing of the owner's. No paid API, no secrets. Sample pages stay in `data_dir` unless the owner approves a trimmed copy.

## Start prompt (paste into a new Claude Code session on pc-01, Sonnet, repo lfmap; owner writes the approval in that session)

```
Task WEB-3 of lfmap #218 (real check of web.fetch on DIEP-ANH). Read docs/handoff/2026-11-12-web3-real-check-card.md and docs/specs/web-plugin.md sections 3, 8, 12, 16. WEB-1 and WEB-2 must be on main and D:\lfmap-runtime updated; if not, stop and say so.
Scope: only docs/research/2026-11-xx-web-fetch-real-check.md and changelog.d/218-web-real-check.added.md. No code under packages/ or plugins/, no ADR edit, no config.toml change by you (the owner added the two hosts).
Do the steps of the card in order: dry checks, ONE real `lfmap web fetch <url> --save` per site from the interactive terminal, compare with the browser view, check audit.jsonl, replay offline, write the report with a verdict (a)/(b)/(c) per site. Do not retry on 403/429 and do not change headers. Stop on any condition in the card.
Commit trailers: Dev-Environment: pc-01. Draft PR with "Refs #218" (never Closes). Report the PR link.
```

## Review checklist for the thread (after the PR)

- Only the report and fragment changed; no sample with real tender text committed without the owner's yes.
- The report has the table of step 8 for both sites and a verdict with evidence.
- Audit numbers in the report agree with the saved file sizes.
- If a verdict is (b) or (c), open or update the G4 row in #218 and tell the owner; do not start a browser plugin.
- After the merge: tick G1 and G4-fetch in the #218 table; S1's daily job may be switched on only if WEB-1 and WEB-2 are merged and the verdict is (a).
