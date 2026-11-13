# Handoff addendum: re-check card for `baodauthau.vn` after WEB-4 (#289, #218 G4)

Follows [WEB-3 card](2026-11-12-web3-real-check-card.md) and its [report](../research/2026-11-13-web-fetch-real-check.md); WEB-4 ([#289](https://github.com/hungnp1999/lfmap/issues/289), PR #292) is merged and lets `web.fetch` read `gzip` and `deflate` pages.

## Task card

- Task: WEB-4b, repeat the one failed request of WEB-3 that WEB-4 should fix. Roadmap: Phase 2, #218 G4.
- Labels: `exec:CC`, `P2`, `res:Local`.
- Executor: Claude Code session on DIEP-ANH (pc-01), run as `lfmap-agent` like WEB-3, model Sonnet, started by the owner. Size: about 15 minutes.
- Blocked by: none (WEB-4 merged).

## Setup (same as WEB-3, not `D:\lfmap-runtime`)

- Worktree `D:\Development\lfmap-web3`, owned by `lfmap-agent`. Config: `C:\Users\lfmap-agent\AppData\Local\lfmap\config.toml`, `[web] allowed_hosts` already holds `baodauthau.vn`, `api.baodauthau.vn`, `muasamcong.mof.gov.vn`. Do not change the config.
- The branch `claude/web3-real-check` there is stale (its PR #288 is merged). Update the worktree to current `main` with a new branch:
  `git -C D:\Development\lfmap-web3 fetch origin main`, then `git -C D:\Development\lfmap-web3 switch -c claude/web4-recheck origin/main` (if the tree is dirty, stop and report; do not discard anything).
- `uv sync --directory D:\Development\lfmap-web3`
- Check the code is the new one: `git -C D:\Development\lfmap-web3 log --oneline -3` shows the WEB-4 commit (`read gzip and deflate pages`).

## The one request

Exactly one request, by hand, no retry, no loop:

`uv run --directory D:\Development\lfmap-web3 lfmap web fetch --url https://baodauthau.vn/thong-bao-moi-thau/ --save --json`

Not part of this task: `api.baodauthau.vn` (401 needs browser headers, out of scope), `muasamcong` (TLS failure, POST plus reCAPTCHA, verdict (c)). Do not request them again, do not add headers, do not disable TLS verification.

## Expected result and how to read it

- Success: `status` 200, `content_type` `text/html`, `bytes` greater than 0, `truncated` true or false, `saved_path` set. Compare the saved page with the browser: is the tender list (about 20 notices) in the HTML text, or built by scripts? Record closing date, field and bidding-form fields visible, charset, size.
- Still `bad_response`: the message now names the header and value (for example `Unsupported Content-Encoding from the page: br`). Record it exactly; `br` would mean a new decision (not part of this task).
- Other refusal (`http_403`, `http_429`, `timeout`, `tls`): record the reason and stop; no retry, no header or `User-Agent` change.
- Audit: `audit.jsonl` of the same account gets exactly one `sent` then one result line, host `baodauthau.vn`, `bytes_in` equal to the saved file size when saved, no URL path, query or page text.

## File scope

May create or edit only: an addendum section "WEB-4 re-check (2026-11-13)" at the end of `docs/research/2026-11-13-web-fetch-real-check.md` (English: result, fields above, verdict (a), (b) or (c) for `baodauthau.vn` with evidence, what it means for G4) and `changelog.d/218-web-recheck.added.md`. No file under `packages/`, `plugins/` or any config. Saved pages stay in `data_dir`; a trimmed sample goes in the repo only if the owner agrees.

## Stop conditions

Stop and tell the owner if: the request goes to another host; the audit shows a URL or page text; the site asks for a login or captcha; the result suggests a fetcher change (file an issue instead).

## Session protocol

1. Open a draft PR at your first commit (`Refs #218`, `Refs #289`, no `Closes`).
2. Post your final report as a PR comment whose first line is `DONE`: result, verdict, audit check, anything not verified.
3. Do not merge. The reviewing thread merges the docs PR when CI is green.

## Start prompt (paste into a new Claude Code session on DIEP-ANH, run as lfmap-agent, model Sonnet)

```
Task WEB-4b of lfmap #218: repeat the baodauthau.vn listing request after WEB-4. Read docs/handoff/2026-11-13-web-4-recheck-card.md in the lfmap repo (origin/main) first, then docs/research/2026-11-13-web-fetch-real-check.md. Work in D:\Development\lfmap-web3 on a new branch claude/web4-recheck from origin/main; uv sync; verify the WEB-4 commit is present.

Make exactly ONE real request, by hand: uv run --directory D:\Development\lfmap-web3 lfmap web fetch --url https://baodauthau.vn/thong-bao-moi-thau/ --save --json. No retry, no other host, no new header, no config change, TLS verification stays on. Compare the saved page with the browser view if you can; check audit.jsonl (one sent line plus one result line, host only).

File scope: addendum at the end of docs/research/2026-11-13-web-fetch-real-check.md and changelog.d/218-web-recheck.added.md. Nothing under packages/ or plugins/. English only. Commit trailers: Dev-Environment: pc-01. Open a draft PR at your first commit (Refs #218, Refs #289). Post your final report as a PR comment whose first line is exactly DONE. Do not merge. Stop and report on a stop condition of the card.
```
