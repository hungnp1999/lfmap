# Leading shadow tally on real LFMAP code (ADR-022 input)

- Date: 2026-11-08. Model: `qwen3.8:27b` (Leading, `num_gpu` 54, temperature 0, `num_ctx` 16384, `num_predict` 8192, thinking on), plain variant, F7 checks on, one review round per case, no pytest gate (the cards have no `tests`).
- Cases: [`spikes/2a1-framework/cases`](../../spikes/2a1-framework/cases/README.md), `FL*-real` (4 real modules of PRs #173, #174, #176, written by a Sonnet Working session, expected `ready`) and `FL*-seed-*` (11 copies with one seeded bug each). Raw results: `D:\Development\lfmap-tonight-state` and `lfmap-seeds-state` on DIEP-ANH.
- Use: input for the ADR-022 amendment (Option B, gate #184). This note decides nothing.

## 1. Real code, expected `ready` (4 cases)

| Case | Raw verdict | Findings | Seconds |
| --- | --- | --- | --- |
| FL2-real (`flows_run.py`) | rework | 1 false: "287 lines, limit 230" (read the hunk header; the harness counter gives 223) | 694 |
| FL1-real (`flows.py`) | rework | 1 weak: `load_flows_file(path)` has no `require_read` (the path is the user's own config file) | 261 |
| FL1b-real (`flows_refs.py`) | ready | none | 217 |
| FL3-real (`flows_triggers.py`) | ready | none | 453 |

0 invented quotes. Recall of the 8 minor known issues: 0/8. The gates (not the model) decided `ready` in 4/4.

## 2. Seeds on real code (11 cases)

| Seed | Leading | Gate |
| --- | --- | --- |
| FL2-exists (hard) | caught, right line | none |
| FL2-swallow | invalid_json | ruff_extra |
| FL2-wrongprop | invalid_json | none |
| FL2-bytes (hard) | invalid_json | none |
| FL1-default | missed (the false `require_read` finding only) | ruff |
| FL1-boundary | missed (same false finding) | none |
| FL1b-truthy | caught | none |
| FL1b-embed | caught | none |
| FL3-loop (hard) | invalid_json | none |
| FL3-idem | caught | none |
| FL3-swallow | caught | ruff_extra |

- **Real catches: 5 of 11** (5 of the 7 replies that were valid JSON). The harness reported 6/11: `FL1-seed-default` was credited because the keyword `state` matched "the rule states". The keywords of the 11 cases were too generic (`state`, `or`, `and`, `list`, `dict`) and were replaced by specific phrases afterwards.
- Any signal (Leading finding or failed gate): 7/11. Seen by nobody: wrongprop, bytes, boundary, loop.
- Hard seeds (no test, no ruff rule): 1/3 caught; the other two are `invalid_json`, so they say nothing about capability yet.
- 0 invented quotes in all 15 reviews. Median review time 261 s (range 93 to 694 s).
- **`invalid_json` is the output cap**: 4 of 11 replies stop after about 590 s, which at 14 tok/s is the `num_predict` cap of 8192 tokens used up by thinking. Not yet re-run with a larger cap (`LFMAP_NUM_CTX`, `LFMAP_NUM_PREDICT` now override the defaults).
- The card rule "caller-supplied paths go through the permission checks" made the model flag `load_flows_file(path)` in 3 of 3 runs on `flows.py`. The wording now separates operation-supplied paths from configuration paths.

## 3. Against the swap criteria (draft §7a, accepted 2026-11-07)

| Criterion | Value | Met |
| --- | --- | --- |
| at least 80 % of at least 12 seeds | 5/11 (45 %); 5/7 (71 %) on valid replies | no |
| 0 invented quotes | 0 of 15 reviews | yes |
| median at most 120 s | 261 s | no |

Conclusion for ADR-022: local Leading stays in shadow mode. The false positives on clean real code (2 of 4) and the missed minor issues (0/8) argue against using it as a filter in front of the Cloud review. What to do next: re-run the 4 `invalid_json` cases with a larger cap, then decide whether a longer thinking budget or a different thinking level changes the picture.
