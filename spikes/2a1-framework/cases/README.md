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

## Replay semantics

`run.py run --case <name>` makes a one-card package. Plan is skipped; Work round 1 writes the files of `diff.patch` and runs the gates, but its result is never retried for a gate failure, so the Leading review always sees the case's diff verbatim (with the gate log, or with `test.log` when no worktree is given). A `rework` verdict sends the card to the Working model as usual.
