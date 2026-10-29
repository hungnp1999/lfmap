# iso-vi: get_context relevance bench

A synthetic corpus of 30 Vietnamese ISO 9001/14001/45001 documents of a fictional company "ABC" (procedures, forms, internal audit reports), written for this bench. It holds no real data.

`questions.json` has 9 questions (5 semantic, 4 keyword). Each lists the `gold` documents that answer it and `acceptable` documents that are related. `context_bench.py` runs `lfmap knowledge get_context` for each question at `min_relative_score` 0, 0.3, 0.4 and 0.5 and reports chunks, tokens, precision (gold or acceptable chunks / kept) and gold-file recall.

Run it against an index that holds only `docs/`, for example with an isolated `LOCALAPPDATA` whose `config.toml` has:

```toml
[paths]
knowledge = ['<repo>\packages\lfmap-knowledge\bench\iso-vi\docs']
```

then `uv run lfmap knowledge reindex --json` and `uv run python packages/lfmap-knowledge/bench/iso-vi/context_bench.py --out result.md`.
