# Leading bench for the two-stage review (tasks A1 and A2)

Status: done 2026-11-06 (Cloud); A3 run, two-stage rejected (see Outcome). Plan: `2026-11-06-leading-speed-plan.md` (project files, backlog #181). 

The bench lives in the project files (`leading-bench/`; a copy is committed as `spikes/leading-bench/` because the Windows PC cannot read the project files; copied to `D:\Development\lfmap-tools\leading-bench` before the run). This note records what changed so the A3/A4 results can be read against it.

## A1: case set

The set grew from 15 cases / 8 seeds to **20 cases / 12 seeds**. The added cases are not new work: the F0 task of the framework spike already built them in `spikes/2a1-framework/cases/`; they are copied unchanged.

| Added case | Kind |
| --- | --- |
| `K4-clean-seed-exists` | caller path probed before the permission check |
| `K4-clean-seed-swallow` | swallowed `OSError` |
| `K4-clean-seed-default` | mutable default argument |
| `K6-seed-empty` | emptiness checked before quotes are removed |
| `FL2-real` | `flows_run.py` as merged in #174 (Sonnet code, expected `ready`, three minor known issues) |

Composition: 12 seeded cases (K4 5, K6 4, K7 3), 5 `ready` cases (`K4-clean`, `K6-clean`, `K6-real`, `K7-clean`, `FL2-real`), 2 real qwen outputs with known issues (`K4-real`, `K7-real`) and the red case `K5-red`.

**Clean labels.** B0b asked to re-read `K4-clean` and `K7-clean` (flagged by every configuration). Re-read on 2026-11-06 against the card and the frozen tests (pytest, ruff check and ruff format pass on both): both are card-conformant, so the `ready` label stays. The code has no C1-C4 problem that the card or the tests name; extra hardening beyond the card is not a finding. The re-read is stored in each case's `expected.json` as `label_review` (also on `K6-clean`); `bench.py` ignores the field. The raw B0b answers are on DIEP-ANH and were not available to Cloud, so a model alarm that names a real C1-C4 problem in these three files would reopen the label.

Caveat for A4: the framework spike showed that 6 of the 12 seeds are also visible to deterministic checks; the bench gives the model only the card and the diff, so the 12-seed rate here is the model-only rate.

## A2: bench changes

`bench.py`:
- `--repeats N`: N reviews per case and model (default 1).
- `--num-gpu N`: passes Ollama `num_gpu` for reviews (A3 uses 54 for `qwen3.8:27b`).
- `--out DIR`: use that folder; if it exists the run is **resumed** and finished runs are skipped. A failed call (timeout, connection) prints `failed` and the loop continues; running the same command again fills the gaps.
- `--cases A B`, `--url URL`: select cases, point at another Ollama (used by the offline test).
- One JSON per run in `<out>/runs/<model>__think-<x>__<case>__r<k>.json`: verdict, every finding with a `valid` flag (quote found in the diff), seeds and seeds caught, `wall_s`, tokens, `done_reason`, GPU share, raw answer and thinking. `reviews.csv` gets the same row with `repeat` and `num_gpu`.
- The GPU is unloaded and `/api/ps` checked before each model; a busy GPU prints a warning.
- `ollama` or `nvidia-smi` missing no longer crashes the script.

`aggregate_twostage.py --stage1 <gpt-oss out> --stage2 <qwen out> [--json file]` pairs the two result sets by case and repeat and applies the rule fixed in the plan: stage 1 `ready` with no finding is accepted without stage 2; everything else takes stage 2's result and costs both times. It prints per-run rows, qwen alone vs pipeline (seeds caught, invented quotes, ready cases not ready) and the four win/lose criteria with `RESULT: WIN|LOSE`. A "false-ready seed" is a seed repeat hidden behind an accepted stage-1 `ready`.

Tests: `python -m unittest test_leading_bench` in the bench folder (6 tests, a fake Ollama on loopback, no GPU): repeats, `num_gpu` passed, resume skips finished runs, 20 cases / 12 seeds, pipeline rule, false-ready, invented quotes, unpaired runs.

## Outcome

A3 ran on DIEP-ANH on 2026-11-06 (qwen3.8:27b, then gpt-oss:20b, 3 repeats). The owner decided afterwards that the two-stage review is rejected and plan B is parked; backlog #181 is closed. The per-run JSON and the `aggregate_twostage.py` printout did not reach the project files from the Cloud side, so this note records no numbers; they stay in `D:\Development\lfmap-tools\leading-bench\out\A3-qwen` and `A3-gptoss` on the PC. The 20-case bench, `--repeats` and the aggregator stay in the repo for future model checks (rerun: `python aggregate_twostage.py --stage1 out/A3-gptoss --stage2 out/A3-qwen`).

## Project documents to update

None for A1/A2. ADR-022 gets the A3/A4 result.
