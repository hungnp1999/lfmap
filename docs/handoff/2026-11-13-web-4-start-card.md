# Handoff addendum: start card for WEB-4 (compressed pages in `web.fetch`, #218 G1)

Issue: WEB-4 [#289](https://github.com/hungnp1999/lfmap/issues/289). Spec: [docs/specs/web-plugin.md](../specs/web-plugin.md), sections 4 (Compression), 5 step 8, 6, 8, 10, 11 (four `WEB-4` tests), 13 and 16.5 (owner decision of 2026-11-13). Parent: #218 (do not close it). Evidence: [docs/research/2026-11-13-web-fetch-real-check.md](../research/2026-11-13-web-fetch-real-check.md) (PR #288): `baodauthau.vn` answered with a compressed body and was refused as `bad_response`. Card format follows [2026-11-12-web-2-start-card.md](2026-11-12-web-2-start-card.md).

## Task card

- Task: WEB-4, let the core fetcher read `gzip` and `deflate` bodies with bounded decompression. Roadmap: Phase 2, #218 G1 (follow-up to WEB-3).
- Labels: `exec:CC`, `P1`, `security-review`.
- Executor: Claude Code, Cloud, **Sonnet**. One PR, draft, `Closes #289` and `Refs #218`.
- Blocked by: none (WEB-1 #277, WEB-2 #278 and the WEB-3 report #288 are on `main`).
- Size: small (one source file, three test files).
- Resource: none (Cloud, offline). The real check on `baodauthau.vn` is redone by the owner on DIEP-ANH afterwards (not part of this task).

## Session protocol (standing rule of the owner, 2026-11-13)

1. Open the **draft PR at your first commit** (title `feat(web): read gzip and deflate pages (WEB-4)`, body from the PR template, `Closes #289`, `Refs #218`), so the reviewing thread can subscribe to it from the start. Keep it a draft until CI is green.
2. Post your **final report as a PR comment whose first line is `DONE`**, followed by: what changed, test results (including the Linux baseline failures), `/security-review` findings and your answers, open questions. Post it only when the work is complete and CI on the head commit is green or you state exactly why it is not. Do not post `DONE` earlier.
3. Do not merge. The reviewing thread starts the review when it sees `DONE` with green CI.

## Decisions already taken (do not reopen)

Owner, 2026-11-13 (spec section 16.5):

1. Allow `gzip` and `deflate`, with bounded decompression. The cap (`max_bytes`, default 2 MiB) applies to the **decompressed** output and decompression stops as soon as the cap is reached.
2. `br`, `zstd` and everything else stay refused. The error message names the header (`Content-Encoding` or `Transfer-Encoding`) and the value.
3. Standard library only (`zlib`). No new dependency.
4. Out of scope, do not add: browser-style headers (`Origin`, `Referer`, `Cookie`) for `api.baodauthau.vn`; any POST or captcha route for `muasamcong`. The `User-Agent` and the other fixed request headers stay as they are, except `Accept-Encoding`.

Choices made in the spec so the session does not stall (change only with a reason in the PR):

- Request header becomes `Accept-Encoding: gzip, deflate`.
- Accepted `Content-Encoding`: absent, `identity`, `gzip`, `x-gzip`, `deflate` (single token, case-insensitive). `deflate` is zlib-wrapped; if the zlib header is wrong, try a raw deflate stream (`wbits=-15`) once.
- `Transfer-Encoding`: absent, `identity` or `chunked` only. `http.client` already de-chunks.
- Wire bytes read are bounded by cap + 64 KiB; reaching that without the output reaching the cap is `bad_response`. A corrupt or prematurely ended stream before the cap is `bad_response` and returns no partial text.
- Output reaching the cap: `truncated = true`, no error (as for plain bodies). `bytes` and the audit `bytes_in` count decompressed bytes. A saved copy holds the decompressed bytes.
- On an error status (4xx or 5xx) the existing rule stays: the body is read only when the encoding is accepted; a refused encoding must not hide the `http_<code>` reason.

## File scope (required)

May edit:

- `packages/lfmap-core/src/lfmap_core/web_http.py` (request header, `_respond`, `_read`, a small decoder helper in the same file or in `web_decode.py` if it keeps the file readable)
- `packages/lfmap-core/tests/test_web_fetch.py`, `test_web_audit.py` (tests below, plus the three existing assertions that pin `Accept-Encoding: identity`: `test_web_fetch.py` line ~197, `test_web_audit.py` line ~34, and the `Content-Encoding: gzip` block of `test_non_text_content_type_refused`; update them to the new rule, do not weaken anything else)
- `packages/lfmap-core/tests/` new file `test_web_encoding.py` (the four new tests and a small gzip/deflate server helper)
- `changelog.d/218-web-compressed-pages.changed.md`
- `docs/specs/web-plugin.md`: only to fix a mismatch you find between spec and code, listed in the PR

Must not touch: `web.py`, `web_rate.py`, `web_egress.py`, the allow-list, address, redirect, rate or audit-order logic, `plugins/`, ADR files, `config.toml` handling, adapters. If the change seems to need one of them, stop and report on the issue.

## Steps

1. Read the spec sections above, `web_http.py` (`_respond`, `_read`, `_request`) and the existing `test_web_fetch.py` server fixture and `guard`.
2. Write the four frozen tests first (names below) and update the three pinned assertions; run them and see them fail for the right reason.
3. Implement: send `Accept-Encoding: gzip, deflate`; parse the two headers into an accepted/refused decision before reading the body (message names the header and value, cut to 50 printable ASCII characters); read through `zlib.decompressobj` in bounded steps (`decompress(data, max_length)` with the unconsumed tail loop), never materialise more than the cap plus one chunk; stop at the cap; keep the wall-clock deadline and the progress counter working; at end of wire data check `decompressobj.eof` (cap not reached and not eof is `bad_response`).
4. Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` (7 `test_jobs_doctor` failures on Linux are the known baseline; compare, do not "fix" them).
5. Open the draft PR at the first commit, then run `/security-review` on the diff and answer every finding in the PR.

## Frozen tests (exact names; spec section 11)

In `packages/lfmap-core/tests/test_web_encoding.py`:

- `test_gzip_and_deflate_decoded`
- `test_zip_bomb_stops_at_cap`: a gzip body of about 1 MiB on the wire (deflate cannot compress beyond about 1032:1) that expands to 1 GiB of zeros with `max_bytes = 1_048_576`; asserts `truncated`, `bytes == 1_048_576`, peak memory below 8 MiB (`tracemalloc`), the call finishes well inside `timeout_s`; also the exact-cap case and the wire-bound case. The bomb is generated in the test (`zlib.compressobj`), never committed.
- `test_unsupported_encoding_refused`: `br`, `zstd`, `compress`, `gzip, gzip`, `gzip, br`, `foo`, `Transfer-Encoding: gzip`; message names the header; body not read; `http_404` with `br` keeps its reason.
- `test_corrupt_compressed_stream`

Hand-write expected values; do not derive them from the code under test. All tests offline (fake HTTPS server on loopback, resolver stub, socket guard). No test resolves a real name.

## Completion criteria

- [ ] The four frozen tests pass on CI; every other WEB-1/WEB-2 test green (only the three pinned assertions changed)
- [ ] Memory and time bound shown by `test_zip_bomb_stops_at_cap`
- [ ] Error message for a refused encoding names `Content-Encoding` or `Transfer-Encoding` and the value
- [ ] No change outside the file scope; no new dependency (`uv.lock` unchanged)
- [ ] `/security-review` run and every finding answered in the PR
- [ ] Changelog fragment present; CodeQL and tests green
- [ ] Draft PR opened at the first commit; final report posted as a PR comment starting `DONE`

## Start prompt (paste into a new Claude Code Cloud session, model Sonnet, repo lfmap)

```
Task WEB-4 of lfmap #218: web.fetch reads gzip and deflate pages with bounded decompression. Read docs/handoff/2026-11-13-web-4-start-card.md first, then docs/specs/web-plugin.md sections 4 (Compression), 5 step 8, 6, 8, 10, 11 (the four WEB-4 tests), 13, 16.5, and packages/lfmap-core/src/lfmap_core/web_http.py and tests/test_web_fetch.py. Branch from up-to-date main; merge origin/main again before push.

File scope: web_http.py (plus an optional small web_decode.py), packages/lfmap-core/tests/test_web_fetch.py, test_web_audit.py, new test_web_encoding.py, changelog.d/218-web-compressed-pages.changed.md. Do not touch web.py, web_rate.py, web_egress.py, plugins/, ADRs, adapters. If you need another file, stop and report on issue #289.

Write the frozen tests first with exactly these names: test_gzip_and_deflate_decoded, test_zip_bomb_stops_at_cap, test_unsupported_encoding_refused, test_corrupt_compressed_stream. Update the three assertions that pin "Accept-Encoding: identity" or the old gzip refusal. Hand-write expected values; all tests offline.

Rules: stdlib zlib only; Accept-Encoding: gzip, deflate; accept only identity, gzip, x-gzip, deflate (single token); br, zstd and anything else refused with bad_response and a message that names the header (Content-Encoding or Transfer-Encoding) and value; the max_bytes cap applies to DECOMPRESSED output, stop decompressing as soon as it is reached (truncated = true), use decompressobj with max_length, wire bytes bounded by cap + 64 KiB, corrupt or cut stream = bad_response; keep the wall-clock deadline; do not add any request header or change any other rule. No captcha or POST work.

Run uv run pytest, uv run ruff check . and uv run ruff format --check . (7 test_jobs_doctor failures on Linux are pre-existing). Commit trailers: Dev-Environment: cloud and Claude-Session (add Dev-Environment by hand if the hook does not). Open the draft PR at your FIRST commit (template, "Refs #218", "Closes #289"). Then run /security-review on the diff and answer every finding in the PR. When complete and CI is green, post your final report as a PR comment whose first line is exactly DONE (what changed, test results, security-review answers, open questions). Do not post DONE earlier. Do not merge.
```

## Review checklist for the thread (after the PR)

- Only files in the scope list changed; `uv.lock` untouched; no new import except `zlib`.
- Cap is on decompressed output; decoder uses `max_length`; nothing builds the full output before checking the cap; the bomb test measures memory.
- Accepted encodings are exactly the list above; `br`, `zstd`, stacked and unknown refused; message names header and value; error-status path still reports `http_<code>`.
- Corrupt or cut stream returns no partial text; wire bound present; deadline still covers decompression.
- Request headers unchanged except `Accept-Encoding`.
- Frozen tests exist with those names and pass; CodeQL green; `/security-review` answered.
- Verdict: Approve / Approve with changes / Reject. Merge (merge by squash, lfmap rule) only when not draft and checks green.
