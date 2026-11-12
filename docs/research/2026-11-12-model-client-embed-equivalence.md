# ModelClient MC-4: embedding equivalence of `/v1/embeddings` and `/api/embed`

Issue #249 (parent #189), spec `docs/specs/model-client.md` section 8, decision 6. Run on `pc-01` (Windows, Ollama 0.40.15, GPU), 2026-11-12 around 23:45 VN. `ollama ps` showed no model loaded before the run.

## Verdict: PASS

`bge-m3` through `OpenAICompatibleClient` against `http://127.0.0.1:11434/v1` returns the same vectors as `OllamaEmbedder` (`/api/embed`). `knowledge` may move to `ctx.models` (MC-5, #250).

| Rule | Result |
| --- | --- |
| Every vector cosine >= 0.9999 with the old one | PASS: 633 vectors, min 0.9999999999999998, mean 1.0, 0 below the bar |
| Equal dimension | PASS: 1024 on both paths |
| Same gold files in the top 10 on all 9 questions | PASS: 9 of 9 (the top-10 file lists are identical) |
| `precision` not lower | PASS: identical at 0, 0.3, 0.4 and 0.5 |
| Token counts not lower | PASS: identical |

Normalisation (reported, not assumed): both paths return L2-normalised vectors, norm between 0.9999994 and 1.0000010 on both. Ollama's `/v1/embeddings` normalises like `/api/embed`.

## Method

`spikes/mc4-embed-equivalence/run.py` (standard library and repo code only):

1. Index the 30 documents of `packages/lfmap-knowledge/bench/iso-vi/docs` twice, into two fresh temporary data folders, once embedding through `OllamaEmbedder`, once through `OpenAICompatibleClient` (batches of 64). Each index is queried by its own embedder. The real knowledge index and the `D:\Development\lfmap-*` state folders were not touched; no environment variable is set (the data folder is passed explicitly, so no separate `LOCALAPPDATA` was needed).
2. Texts: the 133 chunks the indexer produced, plus 500 distinct texts drawn with seed 20261112 from those chunks, their paragraphs, lines and adjacent line pairs (the corpus is too small for 500 distinct chunks). 633 texts were embedded through both paths.
3. Bench: for each of the 9 questions, `search` (limit 10) for the top-10 files and `get_context` at `min_relative_score` 0, 0.3, 0.4 and 0.5 (budget 4000) scored with `context_bench.score`. The complete per-question output of the two indexes is identical (`bench_old == bench_new`).

Average over the 9 questions (same on both paths):

| min_relative_score | tokens | precision |
| --- | --- | --- |
| 0 | 1844 | 0.50 |
| 0.3 | 1659 | 0.54 |
| 0.4 | 1310 | 0.64 |
| 0.5 | 923 | 0.70 |

The verdict logic was first run with a fake embedder in a passing and a failing case (`--fake pass`, `--fake fail`): PASS and FAIL as expected.

## Not done

- The `llama-server` CPU container row is information only and was skipped: no Docker/WSL on `pc-01`.
- Existing vectors stay valid; no reindex is needed when `knowledge` switches.

## Side findings

- `packages/lfmap-knowledge/tests/test_embed.py::test_wrong_vector_count_is_an_error` fails on `pc-01` (`ollama_unreachable` instead of `ollama_bad_response`); this PR does not touch `embed.py`. Not investigated here.
- `uv run ruff check .` reports two unused imports on `main` (`flows_triggers.py`, `test_flows_triggers.py`); not touched here.

## Re-run

```powershell
uv run python spikes/mc4-embed-equivalence/run.py --out D:\Tmp\mc4.json
uv run pytest packages/lfmap-knowledge/tests/test_embed_equivalence_bench.py -m local
```
