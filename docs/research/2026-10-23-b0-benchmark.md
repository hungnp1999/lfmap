# B0 benchmark: Leading Agent candidates on DIEP-ANH

- Date: 2026-10-23, 10:06–12:00Z and 13:41Z (a power or network drop paused the run) · Task L0 of `docs/research/2026-10-23-local-model-tiers.md`
- Environment: DIEP-ANH (RTX 5060 Ti 16 GB, Ollama 0.40.7, Windows), driven by Claude Code through Remote Control; approved by the owner in the project thread (10:01Z, model list changed 10:57Z, valid 24 h). Analysis in a cloud session.
- Script and cases: `D:\Development\lfmap-tools\leading-bench` (outside this repo): `bench.py` (standard library, Ollama HTTP API), 7 review cases, raw answers in `out\<stamp>\answers\`.

## What was measured

- Speed: load time, share of the model on the GPU (`size_vram / size` from `/api/ps`), VRAM used, prompt and generation tok/s for a fixed 600-token coding prompt at `num_ctx` 8192 and 16384.
- Review: one first-pass review per case with the QA standard and a JSON schema (`format`), temperature 0, `num_ctx` 16384. Cases: 4 real diffs from the K4–K7 qwen-loop batch with known verdicts (K4 rework, K5 escalate, K6 ready, K7 rework) and 3 copies of the K6 diff with one seeded bug each (ORDER BY DESC, missing `fold`, SQL built with an f-string).
- Scored by script: verdict, findings whose quoted line exists in the diff (`hallucinated` = quote not found), seeded bug caught (a valid finding quotes the seeded line).

Models: `gpt-oss:20b`, `devstral-small-2:24b`, `qwen3-coder:30b`, `qwen3.8:27b`. `qwen2.5:32b` was dropped by the owner in favour of `qwen3.8:27b` (released 2026-08-14, Apache-2.0). `qwen3.8:27b-nvfp4` could not be pulled: "this model requires MLX support, but the MLX runtime is not available" (MLX is Apple's runtime; not usable on Windows).

## Results

| Model | Size | On GPU | Gen tok/s (8K / 16K) | Correct verdicts | Seeded bugs caught | Hallucinated quotes | Time per review |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `qwen3.8:27b` (dense, thinking on) | 17.7 GB | 67–69 % | 14.0 / 13.9 | **7/7** | **2/3** | **0** | 200–466 s |
| `qwen3-coder:30b` (MoE ~3B active) | 18.6 GB | 67–72 % | 56.3 / 50.0 | 4/7 | 1/3 | 0 | 1–14 s |
| `gpt-oss:20b` (MoE, reasoning) | 13.8 GB | 100 % | 79.8 / 93.6 | 2/7 (4 invalid JSON) | 1/3 | 0 | 48–156 s |
| `devstral-small-2:24b` (dense) | 15.2 GB | 70–79 % | 10.5 / 7.9 | 2/7 | 1/3 | 3 | 2–116 s |

Per case (verdict given, expected in brackets):

| Case | qwen3.8:27b | qwen3-coder:30b | gpt-oss:20b | devstral-small-2:24b |
| --- | --- | --- | --- | --- |
| K4-real (rework) | rework | rework | invalid JSON | ready |
| K5-red (escalate) | **escalate** | rework | rework | rework, 3 invented quotes |
| K6-real (ready) | ready | rework (false alarm) | invalid JSON | ready |
| K6-seed-fold (rework) | rework, missed the seed | ready | rework, missed the seed | ready |
| K6-seed-order (rework) | rework, caught | rework, missed the seed | rework, caught | ready |
| K6-seed-sql (rework) | rework, caught | rework, caught | invalid JSON | rework, caught |
| K7-real (rework) | rework | rework | invalid JSON | ready |

VRAM in use stayed at 13.2–15.1 GB; models above ~14 GB spill to system RAM. Cold loads took 15–47 s, warm reloads 6–16 s, so batch-phase rotation (research note §5) costs about a minute per batch.

## Reading the numbers

- **qwen3.8:27b is the only usable Leading candidate today.** Every verdict right, including the one package that had to go back to Claude (K5), no invented quotes. It is slow because about a third of the model runs from RAM and thinking is on: a batch of 10 reviews takes 40–75 minutes. That fits overnight or background batches, not interactive work.
- **qwen3-coder:30b is fast but not a reviewer.** It flagged a clean diff (K6-real) and passed a broken one (seed-fold). Its speed (≈ 50 tok/s with RAM spill, thanks to MoE) makes it a candidate for the **Working** tier instead; to be compared with `qwen2.5-coder:14b` on the next qwen-loop batch.
- **gpt-oss:20b is not settled.** It is the fastest and fits the GPU, but 4 of 7 answers were not valid JSON. At 88 tok/s and ~150 s per case it produced about 13K tokens, so the reasoning likely ran into the context or the schema; this is probably a harness problem (reasoning level, `format` with a reasoning model), not a verdict on the model. Worth one rerun with the reasoning level set to low.
- **devstral-small-2:24b: drop.** Mostly "ready" on broken code, invented quotes, slowest. Its Ollama package also carries no licence file (`ollama show --license` is empty).
- Against the research thresholds (§3): hallucination ≤ 1 per 10 reviews is met by qwen3.8 (0/7); seeded catch ≥ 80 % is not (2/3, and 3 seeds is a very small sample). So **shadow mode is justified, filter mode is not yet.**

## Limits of this run

- Seven cases, three seeds: indicative only. Whether findings on K4 and K7 match the known issues was not graded (only verdicts); the answers are on DIEP-ANH for a later read.
- One run per model at temperature 0; no repeat for variance.
- Other project threads also use DIEP-ANH; GPU contention during the run was not ruled out.
- The run stopped once (device offline around 12:00Z) and resumed at 13:41Z; each model ran in its own invocation, so no result was lost.

## Decisions taken and next steps

| # | Next step | Environment | Needs owner |
| --- | --- | --- | --- |
| B0b | Rerun `qwen3.8:27b` with thinking off / low and `gpt-oss:20b` with reasoning level low; grow the case set to 10+ seeds (security, off-by-one, missing error) | Local (DIEP-ANH) | yes: new approval sentence in the thread (bench.py needs a `--think` option first, Cloud) |
| L1b | Experience store (§9a); also try `qwen3-coder:30b` as a Working model on the same S cards | Cloud + Local | no |
| L2 | Shadow mode in the 2a.1 spike with `qwen3.8:27b` as Leading model | Local + Claude review | no |
| — | Disk: four models now on D: (~65 GB). `devstral-small-2:24b` (15 GB) can be removed by the owner (`ollama rm`); Claude cannot delete on that device | owner | optional |

Model rows (Internal, Apache-2.0 per `ollama show --license` on 2026-10-23) for `gpt-oss:20b`, `qwen3-coder:30b`, `qwen3.8:27b` go into the License Register (project document, outside this repo).
