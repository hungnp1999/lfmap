# Real check of `web.fetch` on the S1 sites (WEB-3, #270)

Date: 2026-11-13. Machine: DIEP-ANH (pc-01), account `lfmap-agent`. Tracking: #218 (G1, G4). Spec: `docs/specs/web-plugin.md`.

## Summary

All three real requests failed. No page was saved and no page text was read, so no verdict (a), (b) or (c) can be given from evidence about the page content. G1 is **not** confirmed: with the merged fetcher, `web.fetch` does not read either S1 site today.

Note on scope: the start prompt pasted in the session said "one fetch per site, two hosts"; the card and the owner's approval say three requests and three hosts. The card was followed.

## Setup

- `[web] allowed_hosts` of `C:\Users\lfmap-agent\AppData\Local\lfmap\config.toml`: `baodauthau.vn`, `api.baodauthau.vn`, `muasamcong.mof.gov.vn`.
- Dry checks (no network): `https://example.com/` refused (audit `host_not_allowed`); `http://baodauthau.vn/` refused with `invalid_input` ("Only https URLs are fetched"). Both as expected.
- Real requests: one each, `lfmap web fetch --url <URL> --save --json`, by hand, no retry.

## Results

| # | Site / URL | Result | Audit status | `bytes_in` | Saved |
|---|---|---|---|---|---|
| 1 | `baodauthau.vn` listing `/thong-bao-moi-thau/` | `backend_unavailable`: "The page is compressed or has an unsupported transfer encoding" | `bad_response` | 0 | no |
| 2 | `api.baodauthau.vn` `/api/morenews-zone-36-2.html?phrase=&sz=36&st=zone` | `backend_unavailable`: "The page answered HTTP 401" | `http_401` | 0 | no |
| 3 | `muasamcong.mof.gov.vn` `/web/guest/contractor-selection?render=index` | `backend_unavailable`: "TLS verification failed for muasamcong.mof.gov.vn" | `tls` | 0 | no |

Per site: `truncated`, list present, script-built, charset and size are all unknown (no body was returned).

## Audit check

`audit.jsonl` holds, from this session: two `host_not_allowed`/dry-check lines for `example.com` (one pre-dates the session, 06:35), and exactly three `sent` then result pairs for the hosts above (07:20:37, 07:21:29, 07:21:37). Each line carries only host, `bytes_out`, `bytes_in` and status; no URL path, query or page text. `bytes_in` is 0 everywhere, matching the absence of saved files. The `sent` lines show `bytes_out` 252, 286 and 284.

## Findings

1. **baodauthau.vn listing, encoding.** The fetcher refuses the response as compressed or with an unsupported transfer encoding. The message does not say which header triggered it (`Content-Encoding`, `Transfer-Encoding`). Whether the fetcher asks for `identity` and the server ignores it, or the server always compresses, is not known from this run. Fetcher issue to file (not fixed here): the error should name the offending header and value; the encoding policy needs a decision.
2. **api.baodauthau.vn, HTTP 401.** The JSON endpoint answers 401 to a request without `Origin`, `Referer` and whatever else the browser sends (spec section 4 forbids caller headers). It needs credentials or headers `web.fetch` cannot send. Recorded as a finding; no workaround tried. This is a stop condition of the card (needs a header, cookie or login).
3. **muasamcong.mof.gov.vn, TLS.** Certificate verification failed on pc-01. Cause not determined: a certificate chain missing the intermediate (common on Vietnamese government sites), a local trust store, or an interception proxy. The browser opens the site, which suggests the server chain is incomplete and the browser fetches the intermediate itself. Not investigated further; verification was not and must not be disabled. Even if TLS worked, the list is a POST behind reCAPTCHA (owner's browser notes), so the expected verdict remains (c).

## G4 recommendation (provisional)

- **muasamcong:** (c) by the owner's browser findings (POST plus reCAPTCHA); this run only adds the TLS failure and gives no page evidence. Look for an export, notification feature or another public republisher.
- **baodauthau.vn:** open. Direct fetch (a) is blocked by the encoding refusal; the API route is blocked by 401. Possible (b) later, once the encoding issue is decided and the page source or menu is checked for RSS or a public feed. No verdict yet.
- S1's daily job must **not** be switched on.

## Spec change candidates

- Say which header caused `bad_response` in the error message.
- Decide whether `Accept-Encoding: gzip` (with decompression and the byte cap applied after) is allowed; most news sites compress.
- Document the TLS failure mode and that no per-host exception exists.

## Not done

Steps 5 and 7 (comparison with the browser, offline replay) need a saved page; there is none. No sample is added to the repo.

## WEB-4 re-check (2026-11-13)

Task WEB-4b (#218 G4, refs #289). Machine DIEP-ANH (pc-01), account `lfmap-agent`, branch `claude/web4-recheck` from `main` at `e905aff` (contains WEB-4, `2429921`). Config unchanged, TLS verification on, no extra header.

### Result

One real request, by hand: `lfmap web fetch --url https://baodauthau.vn/thong-bao-moi-thau/ --save --json`. No retry. (An earlier attempt from a POSIX shell failed before the program started with `error: The system cannot find the file specified. (os error 2)`; the audit log shows no line for it, so nothing was sent. The command was then run from PowerShell.)

- `status` 200, `content_type` `text/html`, `url_final` equal to the requested URL (no redirect).
- Saved file in `data_dir`: 132 692 bytes, equal to audit `bytes_in`. `truncated` was not read from the JSON (the console output was cut by the session); it is false by inference, since 132 692 bytes is far below the 2 MiB cap.
- Charset: UTF-8 (`<meta http-equiv="Content-Type" ... charset=utf-8>`), no U+FFFD in the decoded text, Vietnamese text intact. `lang="vi"`.
- Comparison with the browser view was not done in this session (no browser); the comparison below is against the saved HTML only.

### What the page holds

- The list is **in the HTML text**, not built by scripts: 61 `<article class="story">` elements (main list plus side blocks), 30 distinct notice links of the form `https://baodauthau.vn/<slug>-post<id>.html`. Each story has a title, a publication timestamp (`story__meta`, e.g. `13/11/2026 00:00`, `12/11/2026 15:02`) and a short summary (`story__summary`).
- Visible fields: title, link, publication date and time, summary. **Not visible in the listing**: closing date, field, bidding form (zero hits for "Thời điểm đóng thầu", "Lĩnh vực", "Hình thức"). They would be in each notice page (not requested; out of scope).
- Items are of mixed kinds: tender notices, quotation requests, expressions of interest; several titles repeat (for example two identical "THƯ MỜI BÀY TỎ QUAN TÂM" entries on the same day), so de-duplication needs the post id.
- Scripts exist (12 `<script>` tags; analytics, ads, a `cmsConfig` block) but the list does not depend on them. No login, captcha or consent wall. No pagination markers were found in the first page (not examined further).
- The head declares an RSS feed: `<link rel="alternate" type="application/rss+xml" href="https://baodauthau.vn/rss/thong-bao-moi-thau-36.rss">`. The feed was **not requested** (not in scope; one request only). Its host is already `baodauthau.vn`, so it is allowed by the current config.

### Audit check

`audit.jsonl` gained exactly two lines for this request: `sent` (`bytes_out` 257) at 16:21:14Z and `ok` (`bytes_in` 132692) at 16:21:15Z, host `baodauthau.vn`. No URL path, query or page text. `bytes_in` equals the saved file size.

### Verdict for `baodauthau.vn`

**(a)** Direct fetch of the listing works and the list is plain HTML. WEB-4 fixed the failure of the first run (the encoding refusal). Evidence: status 200, 132 692 bytes, 30 notice links with title, date and summary in the saved HTML.

### What it means for G4

- G1 is now confirmed for the `baodauthau.vn` listing: `web.fetch` reads it.
- S1 can use this listing for discovery (title, link, date, summary). Closing date, field and bidding form need a second request per notice page; whether that is worth it, or whether the RSS feed (`/rss/thong-bao-moi-thau-36.rss`) carries enough, is the next check, one request, same host.
- `api.baodauthau.vn` (401) and `muasamcong` (TLS, POST plus reCAPTCHA, (c)) are unchanged and were not requested.
- S1's daily job stays off until the notice-page or RSS check is done and the owner decides.

### Not verified

Browser comparison; the `truncated` field as printed; the notice page and RSS contents; pagination; stability of the markup over days.
