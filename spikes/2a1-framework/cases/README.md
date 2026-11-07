# Spike cases

Replay cases for the Phase 2a.1 framework spike (spec `docs/specs/framework-spike.md` section 7). Each folder is one card:

- `card.md`: the task card given to qwen2.5-coder:14b (prompt, API, rules, conftest and frozen tests);
- `diff.patch`: the code under review, a git patch that only adds the card's target file;
- `expected.json`: `id`, `card`, `expected_verdict`, `known_issues`, `seeded` (lines that carry a seeded bug), `keywords` (a finding whose problem names one of them also counts as catching the seed);
- `test.log` (K5 only): the pytest output of the real run.

`packages/K4-K7/package.toml` is the work package for the one Plan run of F4 (TC-K4..TC-K7 of `docs/specs/knowledge.md` section 8 at `c8a4cf4`, in English).

## Origin

The first 15 folders are copied unchanged from `docs/handoff/prep/2026-10-24-framework-spike/cases/` (B0 and B0b set): K4–K7 real qwen output (`*-real`, K5-red), clean reference versions of K4, K6, K7 and eight seeded copies. Task F0 added four seeds of kinds not yet covered, each a copy of a clean case with one change:

| Case | Kind (spec section 7) | Seeded change |
| --- | --- | --- |
| `K4-clean-seed-exists` | caller path used before the permission check | `path.is_file()` before markitdown's `require_read`: a file outside the allowed roots answers `not_found` instead of `permission_denied` |
| `K4-clean-seed-swallow` | swallowed exception | `OSError` from writing the `.json` sidecar caught with `pass` |
| `K6-seed-empty` | missing `ToolError` on bad input | emptiness checked before the quotes are removed, so `'""'` returns an empty FTS5 query |
| `K4-clean-seed-default` | mutable default argument | `config: dict = {}` instead of `None`: shared between calls, and the real config file is never read |

That gives 19 cases with 12 seeds.

## Base commit (K4–K7, PR #26)

Found in the full history (`git fetch --unshallow`; the cloud clone was grafted at `655d175`). PR #26 is merge `ae149fc`; its branch, oldest first:

| Commit | Content |
| --- | --- |
| `c8a4cf4` | parent of the first K4–K7 test commit (`docs: add handoff ...`, on main after #22) |
| `66a383c` | `test(knowledge): add TC-K4 tests for extract` (first test commit) |
| `2218629`, `a91c2c8`, `018ffdf` | tests for K5 chunker, K6 fts, K7 embed |
| `cba8810` | qwen raw output for K4, K6, K7 |
| `781ec55` | Claude's review fixes (also adds tests to `test_embed.py` and `test_extract.py`) |

- Base commit as spec section 7 defines it: **`c8a4cf4`** (`c8a4cf4e043a8f3cf27e7b6433f7451770e5d2bb`).
- Worktree for the gates: **`018ffdf`** (`018ffdf316f8166da5039126a700a2d31d8bb14d`): all four frozen test files of the cards are present and no target module yet. At `c8a4cf4` the test files do not exist, so the pytest gate cannot run there. Every `diff.patch` applies with `git apply` at both commits. The test additions of `781ec55` are not part of the frozen tests; that is why `K4-real` passes them.

## What the deterministic gates see

Checked once on Linux with the lfmap workspace at `018ffdf` (`pytest -q <card test>`, `ruff check`, `ruff format --check` on the target). The gates are part of the flow, so for a seed the Leading review may already have a failing gate log in front of it. Report seed catch rates both over all 12 and over the 6 the gates do not see.

| Case | pytest | ruff check | ruff format |
| --- | --- | --- | --- |
| K4-clean, K4-real, K6-clean, K6-real, K7-clean, K7-real | pass | pass | pass |
| K5-red | 9 of 11 fail | pass | pass |
| K4-clean-seed-order, -unlink, -exists, -swallow; K6-seed-sql; K7-clean-seed-count | pass | pass | pass |
| K4-clean-seed-default | pass | **fail** (B006) | pass |
| K6-seed-empty | 2 fail | pass | pass |
| K6-seed-fold, K6-seed-order | 1 fails | pass | pass |
| K7-clean-seed-proxy, K7-clean-seed-userinfo | 1 fails | pass | pass |

## What the F7 checks see

Task F7 adds two deterministic checks after the gates above (`common/checks.py`; `run.py --no-checks` turns them off): `ruff_extra` (`--select S110,S112,S608`, typed exceptions included) and `probes` (hidden tests in `probes/`, K4 and K7 targets only). Measured on Linux with the workspace at `018ffdf`: they fail on exactly these 8 cases and on none of the other 11.

| Case | Check that fails |
| --- | --- |
| K4-clean-seed-swallow | `ruff_extra` (S110), `probes` |
| K4-clean-seed-exists, -order, -unlink | `probes` |
| K4-real | `probes` (temp file left behind) |
| K6-seed-sql | `ruff_extra` (S608) |
| K7-clean-seed-count | `probes` (card gap: the card never says to check the vector count) |
| K7-real | `ruff_extra` (S110), `probes` |

The probes were written after reading the seeds, so 6/6 is an upper bound, not a blind catch rate.

## Replay semantics

`run.py run --case <name>` makes a one-card package. Plan is skipped; Work round 1 writes the files of `diff.patch` and runs the gates, but its result is never retried for a gate failure, so the Leading review always sees the case's diff verbatim (with the gate log, or with `test.log` when no worktree is given). A `rework` verdict sends the card to the Working model as usual.

## FL2-real (added 2026-11-06)

First case from real LFMAP code instead of qwen output: `flows_run.py` as merged in PR #174 (`ac7ef50`), written by a Sonnet Working session. Expected verdict `ready`; `known_issues` are the three minor points found by a manual read, so it measures false findings and rework verdicts on code that passed CI and `/security-review`.

- Worktree for the gates: `ac7ef50^` plus the frozen tests of #174 (`test_flows_run.py`, `test_flows_run_cli.py`, and the `approval.py`, `approvals.py`, `cli.py`, `flows.py`, `tool.py` changes of that commit), without `flows_run.py`; `diff.patch` adds it. Simplest: a worktree at `ac7ef50` with `flows_run.py` removed.
- Run with `--no-checks` off (F7 checks on). Run one round only: a `rework` verdict would send the card to the Working model, which is not wanted for this case, so stop after the first Leading review and keep `state-dir`.

## FL1-real, FL1b-real, FL3-real (added 2026-11-07)

Three more real-code cases, same shape as FL2-real (expected `ready`, `known_issues` = residual points found by a manual read, not seeds): `flows.py` and `flows_refs.py` as merged in PR #173 (`45a1039`), `flows_triggers.py` as merged in PR #176 (`a3fe9b7`). Together with FL2-real they give four real-code cases for the shadow tally (ADR-022).

- Gate worktree: detached at the PR's merge commit with only the case's target file removed (`diff.patch` adds it back); the card has no `tests`, so the pytest gate and probes do not run, as for FL2-real.
- One Leading round per case (see the FL2-real note); repeats at temperature 0 are near-identical, so one run per case.
