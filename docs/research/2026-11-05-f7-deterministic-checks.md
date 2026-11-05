# F7: deterministic checks for the gate-invisible seeds

- Date: 2026-11-05
- Issue: #154 (follows F6, PR #153; F5 report `docs/research/2026-11-04-framework-spike.md` section 3)
- Status: design, awaiting Hùng's decision (gate 1, Friday 06/11 17:00 VN)
- Handoff for the build: `docs/handoff/2026-11-05-f7-deterministic-checks.md`

## 1. Problem

In the F6 shadow re-run the deterministic gates (scope, frozen tests unchanged, `ruff check`, `ruff format --check`, `pytest`) are green on six seeded cases and on `K4-real` and `K7-real`, so only the Leading review could catch them. It misses `exists`, `swallow` and `count` in all three variants, even with S1, S2 and S6 of the checklist naming those kinds. ADR-022 stays Proposed while the review layer lets these through. The issue's rule: no more prompt tuning; find a deterministic check per kind or record a known limit.

## 2. Result in one line

Two cheap checks catch all six seeds and both real cases, with no false alarm on the 11 other cases. Measured on Cloud on 2026-11-05 against the lfmap workspace at `018ffdf` with a throw-away reference implementation (not committed); the frozen tests in `docs/handoff/prep/2026-11-05-f7/tests/` reproduce it.

| Check | What it is | Cost |
| --- | --- | --- |
| `ruff_extra` | `ruff check --isolated --line-length 120 --select S110,S112,S608 --config "lint.flake8-bandit.check-typed-exception = true" <target>` | config only, ruff already pinned |
| `probes` | hidden pytest files per target module, copied next to the card's frozen tests for one run, then removed | 5 probe tests (about 130 lines, written), about 1 s per card |

## 3. Per seed kind

| Seed (case) | Check that catches it | Why it works | False-positive risk |
| --- | --- | --- | --- |
| `swallow` (`K4-clean-seed-swallow`) | `ruff_extra` S110 with `check-typed-exception = true`; probe `test_probe_write_error_is_raised` | `except OSError: pass`. Default S110 only flags bare `except`/`Exception`, hence the option. | Low. Intentional swallow needs `# noqa: S110` plus a reason. Also flags `K7-real` (`except (AddressValueError, ValueError): pass` before a raise), which is a rework case anyway. |
| `sql` (`K6-seed-sql`) | `ruff_extra` S608 | f-string SQL | Low to medium: also flags safe f-strings that only insert constant table names. Not seen in the 19 cases. |
| `exists` (`K4-clean-seed-exists`) | probe `test_probe_permission_before_existence` | a missing file outside the allowed roots must answer `permission_denied`; the seed answers `not_found` | Low: behaviour, not syntax. A generic AST rule ("file-system probe on a parameter before `require_*`") was rejected: in K4 the permission check is inside the delegated `MarkitdownTool.convert`, so the rule would need a per-card allow list. |
| `order` (`K4-clean-seed-order`) | probe `test_probe_sidecar_written_last` | `os.replace` fails for the `.md`; then no `.json` may exist | Low. If the module does not write through `os.replace`, the probe skips (inconclusive, never red). |
| `unlink` (`K4-clean-seed-unlink`) | probe `test_probe_no_temp_files_after_failed_write` | every `os.replace` fails; the cache folder must be empty afterwards | Low. Same skip rule. Also catches `K4-real` (temp file not removed). An AST rule (`mkstemp` without `unlink` in `except`/`finally`) works too but adds a component for no extra catch. |
| `count` (`K7-clean-seed-count`) | probe `test_probe_vector_count_is_checked` | loopback fake Ollama returns one vector fewer than inputs; `embed` must raise `ToolError` | Low. **Card gap:** the K7 card says "return all vectors in input order" but never says "check the count"; the probe encodes `expected.json`'s known issue. Also catches `K7-real`. |

Rejected for every kind: mutation-style probes (mutating the diff and re-running the frozen tests). They measure how strong the frozen tests are, not whether the diff is wrong, and cost one pytest run per mutant.

## 4. Measured matrix (19 cases, Cloud, workspace `018ffdf`)

- Caught by the new checks (8): `K4-clean-seed-exists`, `-swallow`, `-order`, `-unlink`, `K6-seed-sql`, `K7-clean-seed-count`, `K4-real`, `K7-real`.
- Not flagged by the new checks (11): the three clean references, `K6-real` (expected `ready`), `K5-red`, `K4-clean-seed-default`, `K6-seed-empty`, `K6-seed-fold`, `K6-seed-order`, `K7-clean-seed-proxy`, `K7-clean-seed-userinfo`. All except the clean references and `K6-real` are already red on the F6 gates.
- Together with F6's gates, every case whose `expected_verdict` is `rework` (14, all 12 seeds included) now has at least one red gate, and the four `ready` cases (`K4-clean`, `K6-clean`, `K7-clean`, `K6-real`) stay green. `K5-red` (`escalate`) was already red.

Limits of this measure:

- The probes were written after reading the seeds and the answer key, so 6/6 is an upper bound, not a blind catch rate. They test rules the card or the repo security rules state (K4: "`.md` first, `.json` last", "leave no temp files"; CLAUDE.md permission rule), except `count` (card gap above).
- Probes exist only for the K4 and K7 targets. A new card gets this protection only if its author writes probes; that is the Planner's job in 2a.2, not the review's.

## 5. Where the checks run

- New module `spikes/2a1-framework/common/checks.py` with `run_checks(package, card) -> list[GateResult]`, gate names `ruff_extra` and `probes` (`CHECK_GATES`).
- `common/gates.run_gates` appends `run_checks(...)` after `pytest`, so the checks run **before** the Leading review and their log reaches it through `review_log`; `gate_verdict` turns any red check into `rework` with no other change.
- `Package.checks: bool = True` and `run.py --no-checks` keep an F6-comparable run possible.
- Probe files live in `spikes/2a1-framework/probes/`, mapped by target path in `checks.PROBES`. They run with `package.pytest_cmd` from the folder of `card.tests[0]` (so the package `conftest.py` applies), are deleted in `finally`, and only run when the card has frozen tests. The scope and frozen-test gates take their snapshot before the probes are copied, so they never see them.

## 6. Score changes (`score.py`)

- `checks_caught(attempt) -> bool`: a gate in `CHECK_GATES` failed on the first attempt.
- New columns per variant: seeds caught by the checks, seeds caught by checks or review, and check alarms on cases whose `expected_verdict` is `ready`.
- The existing "seeds caught" column (Leading review alone) stays, so F6 and F7 compare directly.

## 7. Decisions for Hùng

1. **ADR-022 measure.** Option A (recommended): the filter-mode thresholds apply to the whole review layer (gates + checks + Leading review); the Leading-alone figure is still reported. Option B: keep the thresholds on the Leading review alone; then `exists`, `swallow` and `count` are recorded as known limits and ADR-022 likely stays Proposed. A changes how an ADR is measured, so it is your call.
2. **Seeded re-run on DIEP-ANH.** The checks are deterministic; the 19-case matrix runs on Cloud in about a minute. Option A (recommended): drop the Saturday 2 h GPU slot; Cloud runs the matrix, and the Leading model is re-run only at the next real Plan run. Option B: keep the slot to see whether the Leading review names the bugs once a red check log is in front of it.
3. **Card gap (`count`).** Recommended: keep the probe, mark it as a card gap in the report, and add "check the shape and count of external replies" to the Planner card checklist for 2a.2. No ADR change.

Not a decision: S110/S112/S608 stay spike-only. Adding them to the root `ruff.toml` is a separate backlog issue (it would flag existing code to review first).
