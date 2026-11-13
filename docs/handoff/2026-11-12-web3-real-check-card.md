# Handoff addendum: task card for WEB-3 (real check of `web.fetch` on DIEP-ANH)

Issue: [#270](https://github.com/hungnp1999/lfmap/issues/270). Parent handoff: [2026-11-11-web-plugin-spec-g1.md](2026-11-11-web-plugin-spec-g1.md). Spec: [docs/specs/web-plugin.md](../specs/web-plugin.md) (sections 3, 8, 12, 14, 16). Tracking issue: #218 (gap G1, folds into G4; this task never closes it). Scenario: S1 in [acceptance-scenarios.md](../specs/acceptance-scenarios.md). Card format follows [2026-11-11-dc4-start-card.md](2026-11-11-dc4-start-card.md).

## Task card

- Task: WEB-3, real check of `web.fetch` on the two S1 sites. Roadmap: Phase 2, #218 G1 / G4.
- Labels: `exec:CC`, `P1`, `res:Local`.
- Executor: Claude Code session on DIEP-ANH (pc-01) started by the owner. Model: Sonnet. Cloud sessions never fetch the real sites (spec section 12).
- Blocked by: [#269](https://github.com/hungnp1999/lfmap/issues/269) (WEB-1, core fetcher) and [#271](https://github.com/hungnp1999/lfmap/issues/271) (WEB-2, plugin `lfmap-web`), both merged (PR #277, PR #278, 2026-11-13), and the fresh worktree `D:\Development\lfmap-web3` (branch `claude/web3-real-check`, from `origin/main`, made by `lfmap-agent`; the old clone `D:\Development\lfmap` sits on `ag/spike-f6-results` and is not used) (ADR-023; `D:\lfmap-runtime` serves the owner's scheduled tasks and is not used here). Order: WEB-1, then WEB-2, then this.
- Start when: WEB-2 is merged and the owner has one evening slot with internet. Preflight one day before (below).
- Size: about 1 hour at the machine, no GPU.

## State on main (2026-11-13)

- WEB-1 ([#277](https://github.com/hungnp1999/lfmap/pull/277)) and WEB-2 ([#278](https://github.com/hungnp1999/lfmap/pull/278)) are merged; #269 and #271 are closed, so WEB-3 is unblocked.
- Known deviation ([#281](https://github.com/hungnp1999/lfmap/issues/281)): `--save` writes the page as UTF-8 text, not the raw body bytes the spec asks for. Fine for this check if both sites are UTF-8: check the `Content-Type` charset of each response and record it in the report. If a site is not UTF-8, say so as a finding; do not fix the plugin here.
- The owner must set `[web] allowed_hosts` on pc-01 (step 2) before the session starts. Without it every request is refused.

## What the owner saw in the browser (2026-11-13)

- **baodauthau.vn.** Listing page `https://baodauthau.vn/thong-bao-moi-thau/` shows 20 notices; "XEM THÊM" loads 20 more through a GET that returns JSON, for example `https://api.baodauthau.vn/api/morenews-zone-36-2.html?phrase=&sz=36&st=zone` (page 3 is `...-3.html`, same query). The host is **`api.baodauthau.vn`, not the listing host**, so it needs its own entry in `allowed_hosts` (exact matching). The browser also sends `Origin` and `Referer`; `web.fetch` sends neither and a caller cannot add them (spec section 4). If the API answers `403` without them, record it as a finding; do not work around it.
- **muasamcong.mof.gov.vn.** Listing `https://muasamcong.mof.gov.vn/web/guest/contractor-selection?render=index` (10 rows a page, up to 50). The list is loaded by a **POST protected by Google reCAPTCHA**. v1 has no POST and nothing here may try to get past a captcha, so the expected verdict is (c). Alternatives for the owner to weigh later (not part of this task): an export or notification feature of the portal, or another public source that republishes the same tenders.
- Both pages need no login.

## Goal

Show, with three real requests (listing page and one API page for baodauthau.vn, listing page for muasamcong), that the merged `web.fetch` reads the tender listing pages of the two S1 sites as usable text, and record what that means for G4 (fetch directly, or look for an export, RSS or API). Output is a report and two saved sample pages, not product code.

## State to verify first (do not assume)

- WEB-1 and WEB-2 are on `main`; `lfmap web fetch --help` works from `D:\Development\lfmap-web3` (`uv run --directory D:\Development\lfmap-web3 lfmap web fetch --help`).
- The test `test_flow_step_fetch_then_convert` and `test_cli_and_mcp_generated` exist and pass on CI.
- The fixes of spec section 16.4 are in: `test_dns_hang_respects_timeout`, `test_long_query_is_t3`.

If any of this is missing, stop and comment on the issue; do not patch the fetcher in this task.

## File scope (required)

May create:

- `docs/research/2026-11-xx-web-fetch-real-check.md` (report, English)
- `tests/samples/web/` is NOT used. Saved pages go to the plugin `data_dir/pages/` on pc-01 and, only after the owner agrees, a trimmed copy under `docs/specs/acceptance-samples/s1/` (see step 7).
- `changelog.d/218-web-real-check.added.md`

Must not touch: any file under `packages/`, `plugins/`, `config.toml` of the repo, ADRs. The owner edits the config of the account that runs the session by hand: the session runs as `lfmap-agent`, so the file is `C:\Users\lfmap-agent\AppData\Local\lfmap\config.toml` (`%LOCALAPPDATA%\lfmap`, ADR-023), not the owner's own account file.

## Steps

1. **Preflight (the day before, owner, 5 minutes).** Open both sites in a browser. Write down the exact host in the address bar of each listing page (with or without `www`), and whether the page shows tender rows without logging in. Paste the two hosts and two listing URLs into the issue. Matching is exact (spec section 3), so a wrong host fails closed.
2. **Config (owner, by hand).** Add the three exact hosts (`baodauthau.vn`, `api.baodauthau.vn`, `muasamcong.mof.gov.vn`) to `[web] allowed_hosts` in the `config.toml` of the account that runs the session (`lfmap-agent`, see above); `uv run python -c 'from lfmap_core.config import load_config,config_path; from lfmap_core.web import load_web_config; print(config_path()); print(load_web_config(load_config()).allowed_hosts)'` must print the config path and exactly the two hosts (`lfmap config` has no command that prints `[web]`). Leave the other keys at default. Do not set anything else.
3. **Dry checks, no internet.** the one-line check of step 2 shows the three hosts; `lfmap web fetch https://example.com/` is refused with `host_not_allowed` and appends one `web_fetch` audit line; an `http://` URL is refused with `invalid_input`.
4. **Three real requests in all**, from the interactive terminal, by hand, each `lfmap web fetch --url <URL> --save`: the baodauthau.vn listing page, then `https://api.baodauthau.vn/api/morenews-zone-36-2.html?phrase=&sz=36&st=zone` (page 2 only; the pattern for later pages is recorded, not fetched), then the muasamcong listing page. No loop, no further pages. If a site answers `http_403` or `http_429`, stop for that site and record it; do not retry or change the `User-Agent` (spec section 13).
5. **Compare with the browser.** For each saved page: is the tender list present in the HTML text, or is the page a shell built by scripts? Record: closing date, field and bidding-form fields visible or not; `truncated`; encoding problems (Vietnamese diacritics, Russian); size in bytes.
6. **Audit check** (spec section 12 step 4). `audit.jsonl` has exactly three `web_fetch` pairs (`sent`, then `ok` or the error reason), the right hosts, `bytes_in` equal to the saved file sizes, and no URL path, query or page text anywhere in the lines.
7. **Offline replay.** With the network off (or the hosts removed from the allow-list), run a one-step flow or a plain `markitdown`/text read over the saved files to show S1 can be tested without the sites. Do not store real tender data in the repo: if a sample is wanted in the repo, strip it to the structure plus three dummy rows, and ask the owner first (public data, but keep the repo small).
8. **Report.** Write the report: hosts used, date, per site `status`, `bytes`, `truncated`, list present yes/no, script-built yes/no, verdict, and the G4 recommendation: (a) fetch directly in the daily job; (b) the site needs an export, RSS or API (name the one seen in the page source or the site menu); (c) a browser would be needed (then stop: that is a new decision, not part of v1). Also record anything that suggests a spec change (header, content type, charset, redirect to another host, rate).
9. Commit the report and fragment, open a draft PR `Refs #218`, no `Closes`.

## Frozen checks

No new code tests. Pass rule, all of:

- [ ] The three requests of step 4 made once each with a recorded `status` (success or a recorded refusal reason)
- [ ] Audit lines match step 6
- [ ] Verdict for each site is one of (a), (b), (c) with the evidence that supports it
- [ ] No cookie, no second request, no change to the allow-list beyond the three hosts

## Stop conditions

Stop and tell the owner (do not work around) if: a request goes to a host other than the three listed; the audit shows a URL or page text; the fetch needs a header, cookie or login; either site asks for a captcha; a result suggests the fetcher should change (file an issue instead).

## Data and egress

Public pages only, `normal` class. What leaves the machine: three HTTPS GETs (URL, fixed headers). Nothing of the owner's. No paid API, no secrets. Sample pages stay in `data_dir` unless the owner approves a trimmed copy.

## Session protocol

1. Open a draft PR at your first commit (`Refs #218`, and `Closes #270` is allowed here only because this issue is the task, not the tracker).
2. Post your final report as a PR comment whose first line is `DONE`, followed by the verdict per site, the PR checks you ran and anything you could not verify.
3. The thread that owns this card starts the review on `DONE` plus green CI on the head commit.

## Start prompt (paste into a new Claude Code session on pc-01, Sonnet, repo lfmap; owner writes the approval in that session)

```
Task WEB-3 of lfmap #218 (real check of web.fetch on DIEP-ANH). Read docs/handoff/2026-11-12-web3-real-check-card.md and docs/specs/web-plugin.md sections 3, 8, 12, 16. WEB-1 and WEB-2 must be on main and D:\Development\lfmap-web3 prepared (run the commands with `uv run --directory D:\Development\lfmap-web3`); if not, stop and say so.
Scope: only docs/research/2026-11-xx-web-fetch-real-check.md and changelog.d/218-web-real-check.added.md. No code under packages/ or plugins/, no ADR edit, no config.toml change by you (the owner added the three hosts).
Do the steps of the card in order: dry checks, the three real `lfmap web fetch --url <URL> --save` requests of step 4 (one each, from the interactive terminal), compare with the browser view, check audit.jsonl, replay offline, write the report with a verdict (a)/(b)/(c) per site. Do not retry on 403/429 and do not change headers. Stop on any condition in the card.
Commit trailers: Dev-Environment: pc-01. Draft PR with "Refs #218" (never Closes). Follow the Session protocol of the card (draft PR at first commit, final report as a PR comment starting with DONE). Report the PR link.
```

## Review checklist for the thread (after the PR)

- Only the report and fragment changed; no sample with real tender text committed without the owner's yes.
- The report has the table of step 8 for both sites and a verdict with evidence.
- Audit numbers in the report agree with the saved file sizes.
- If a verdict is (b) or (c), open or update the G4 row in #218 and tell the owner; do not start a browser plugin.
- After the merge: tick G1 and G4-fetch in the #218 table; S1's daily job may be switched on only if WEB-1 and WEB-2 are merged and the verdict is (a).
