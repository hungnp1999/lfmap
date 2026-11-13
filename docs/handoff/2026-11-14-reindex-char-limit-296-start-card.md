# Handoff addendum: start card for #296 (reindex stops embedding on long chunks)

Issue: [#296](https://github.com/hungnp1999/lfmap/issues/296) (P1). Source: [docs/research/2026-11-15-modelclient-review.md](../research/2026-11-15-modelclient-review.md) section 3, F1 (review #263, PR #307). Card format follows [2026-11-14-jf-1-start-card.md](2026-11-14-jf-1-start-card.md).

## Task card

- Task: `ModelEmbedder` splits a batch by characters as well as by count, so no embed call exceeds the client limit (`MAX_CONTENT_CHARS`, 200 000 per call, sum of all texts).
- Labels: `exec:CC`, `P1`.
- Executor: Claude Code, Cloud, **Sonnet**. One PR, draft, `Closes #296`.
- Blocked by: none. Resource: none (Cloud, offline, fake `/v1/embeddings` server).
- Size: small (one source file, new tests, one changelog fragment).

## Session protocol (standing rule of the owner, 2026-11-13)

1. Open the **draft PR at your first commit** (title `fix(knowledge): split embed batches by characters (#296)`, body from the PR template, `Closes #296`), so the reviewing thread can subscribe from the start. Keep it a draft until CI is green.
2. Post your **final report as a PR comment whose first line is `DONE`**, followed by: what changed, test results, the decision on an oversized single text, open questions. Post it only when the work is complete and CI on the head commit is green, or state exactly why it is not.
3. Do not merge. The reviewing thread starts the review when it sees `DONE` with green CI.

## Decisions already taken (do not reopen)

- Fix in `ModelEmbedder` (`indexer.py`). The limit in `lfmap_core/models.py` and `models_http.py` is part of the Protocol (spec section 3) and **stays untouched**. Raising the limit for local endpoints was the review's alternative; rejected.
- A new constant in `indexer.py`, `MAX_BATCH_CHARS`, imported from `lfmap_core.models.MAX_CONTENT_CHARS` (do not copy the number). Keep the split a small pure function (texts, count limit, char limit -> list of batches) so it is easy to test.
- Order of vectors must still match the order of texts; `concurrency > 1` still works across the new batches.
- A single text longer than `MAX_CONTENT_CHARS` (practically unreachable: the chunker allows 3 000 characters, but a bad `max_chars` setting could produce it): **truncate it to the limit for the embed call and log one warning** naming the text index and its length. It keeps one vector per text and does not block the batches after it. (Decision by the thread, reversible; flag it in `DONE` if you see a reason to differ.)

## File scope (required)

May change or create: `packages/lfmap-knowledge/src/lfmap_knowledge/indexer.py`, `packages/lfmap-knowledge/tests/` (new file `test_embed_char_batches.py`; no edits to existing test files), `changelog.d/296-embed-char-batches.fixed.md` (see `changelog.d/README.md`).

Must not touch: `lfmap_core/models.py`, `models_http.py`, ADRs, `.claude/`, adapters, `uv.lock`, any other plugin.

## Steps

1. Read `ModelEmbedder` and `_embed` in `indexer.py`, and the fake server in `tests/test_model_embedder.py` (copy its pattern into the new test file; do not import across test modules).
2. Tests first, see them fail for the right reason (expected values hand-written):
   - Unit: texts of 2 000 characters each, 200 of them, count limit 128: every embed request has a character sum of at most 200 000 and at most 128 texts; the returned vectors are in input order (use the fake server's number-from-text pattern).
   - Unit: texts that fit (128 texts of 1 000 characters) still go in **one** request (no needless splitting).
   - Unit: a text of exactly `MAX_CONTENT_CHARS` goes alone and succeeds; a text of `MAX_CONTENT_CHARS + 1` is truncated, one warning is logged (use `caplog`), the texts around it are still embedded, and the vector count equals the text count.
   - Integration (repro of the issue): three Markdown files with 2 400-character paragraphs, reindex through `KnowledgeTool` with the fake server: `embedded` is greater than 0 and equals the number of contents, `embed_skipped_reason` is empty, every request is at most 200 000 characters, and a second reindex makes no embed request.
   - `concurrency = 2` with the split batches keeps the order (reuse the barrier pattern if simple; otherwise assert order on a sequential run and state so).
3. Implement the split in `ModelEmbedder.embed` (greedy: close a batch when adding the next text would pass the count or the character limit).
4. Changelog fragment, one sentence.
5. Run `uv run pytest packages/lfmap-knowledge` then `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`. Merge origin/main again before push.
6. `/security-review` is not required (no path, subprocess, network or `.claude/` change); say so in the PR.

## Frozen tests (must pass without edits)

`tests/test_model_embedder.py`, `tests/test_indexer.py`, `tests/test_tool.py`.

## Completion criteria

- [ ] No embed request exceeds 200 000 characters or the count limit
- [ ] Reindex of long-chunk files embeds everything, second run idempotent
- [ ] Oversized single text warned and truncated, later batches unaffected
- [ ] Frozen tests untouched and green; ruff clean; changelog fragment present; CI green
- [ ] Draft PR at first commit; `DONE` comment posted

## Start prompt (paste into a new Claude Code Cloud session, model Sonnet, repo lfmap)

```
Task #296 of lfmap (P1): `knowledge reindex` stops embedding when a batch of chunks exceeds the 200 000-character embed limit. Read docs/handoff/2026-11-14-reindex-char-limit-296-start-card.md first, then F1 in docs/research/2026-11-15-modelclient-review.md section 3, then ModelEmbedder and _embed in packages/lfmap-knowledge/src/lfmap_knowledge/indexer.py and the fake server in packages/lfmap-knowledge/tests/test_model_embedder.py. Branch from up-to-date main; merge origin/main again before push.

File scope: indexer.py, a NEW test file packages/lfmap-knowledge/tests/test_embed_char_batches.py, changelog.d/296-embed-char-batches.fixed.md. Do not edit existing tests, lfmap_core/models.py, models_http.py, ADRs, .claude/, uv.lock.

Tests first (see them fail), expected values by hand: batches under 200 000 characters and at most 128 texts with vector order kept; fitting texts stay in one request; a text of exactly MAX_CONTENT_CHARS passes alone, one longer is truncated with one logged warning and does not block later batches; repro of the issue (three Markdown files with 2 400-character paragraphs, reindex through KnowledgeTool + fake /v1/embeddings server) embeds everything, no embed_skipped_reason, second run makes no request; concurrency 2 keeps order. Then split batches by characters as well as count in ModelEmbedder.embed (greedy, MAX_BATCH_CHARS imported from lfmap_core.models.MAX_CONTENT_CHARS, small pure helper).

Run uv run pytest, uv run ruff check ., uv run ruff format --check . Commit trailers: Dev-Environment: cloud and Claude-Session. Open the draft PR at your FIRST commit (template, "Closes #296"). /security-review is not needed; say so. When complete and CI is green, post your final report as a PR comment whose first line is exactly DONE (changes, test results, decision on oversized text, open questions). Do not post DONE earlier. Do not merge.
```

## Review checklist for the thread (after the PR)

- Only files in scope changed; `models.py` and `models_http.py` untouched; no new dependency.
- Split is greedy and correct at the boundary (sum equals the limit passes, limit plus one splits); order kept with concurrency.
- Oversized text: warned, truncated, vector count equals text count.
- Frozen tests unedited; repro test fails on main and passes on the branch; CI and CodeQL green.
- Verdict Approve / Approve with changes / Reject. Merge (squash) only when not draft and checks green.
