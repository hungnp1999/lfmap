# Phase 2a.1 framework spike: result (F5)

- Date: 2026-11-04. Task F5 of `docs/handoff/2026-10-24-phase2a-framework-spike.md`; spec `docs/specs/framework-spike.md`.
- Input: the F4 real run, `spikes/2a1-framework/results/2026-11-02/` (PR #149): 3 variants x (19 replay cases + 1 Plan run) = 60 runs on DIEP-ANH (pc-01) under the `lfmap-agent` account, all exit 0, all resumed with `--approve`, 1397 min wall. Leading `qwen3.8:27b` (num_gpu 54), Working `qwen2.5-coder:14b`, Ollama 0.40.13, thinking on.
- **Result: no framework.** `langgraph` fails E8; `plain` beats `pydanticai` 10.0 to 2.5, far from the 1.5-point margin a framework needs. The `plain` variant becomes the base of the Phase 2 orchestration. Draft ADR-024 at the end amends ADR-004.
- **Shadow mode: the Leading review is not ready for filter mode.** On replay cases it catches 9/12 seeds (75 %, threshold 80 %) and only 3 of the 6 seeds the gates cannot see; it rejects every clean reference module; and in the Plan run it approved three modules that do not even import.

Numbering: the handoff calls the result ADR "ADR-023"; that number went to "agents run under a separate Windows account" (2026-10-30), so this report uses **ADR-024** (see `variants/plain/NOTES.md`).

## 1. Exclusion criteria (spec section 3)

| Id | plain | pydanticai | langgraph | How it was checked |
| --- | --- | --- | --- | --- |
| E1 licences | pass | pass | pass | Licence metadata of all 58 distributions in the spike venv with both groups synced (2026-11-04): all MIT, BSD, Apache-2.0, ISC, PSF or MPL-2.0. `regex` (pydanticai) is Apache-2.0 AND CNRI-Python, already a reviewed exception in `scripts/check_licenses.py` |
| E2 no outbound connection | pass | pass | pass | Socket guard in the real run: 0 non-loopback connections, no telemetry variable set (`score.txt`) |
| E3 Windows, Python 3.12, Ollama | pass | pass | pass | F4: 20/20 runs each, exit 0, structured output from both models |
| E4 pause survives process exit | pass | pass | pass | Contract test (run, exit, `resume` in a subprocess) and 20 real resumes per variant |
| E5 offline, fake model, < 30 s | pass (19 s) | pass (18 s) | pass (17 s) | `pytest tests/test_variant_contract.py -k <variant>`, 8 tests each, cloud Linux container, wall time including uv start |
| E6 embeddable as one step | pass | pass | pass | Code review: each variant is `run_flow()` / `resume()` functions; no daemon, server, scheduler or account. `langsmith` is installed with `langgraph` but tracing is off by default |
| E7 batch-phase order | pass | pass | pass | 0 swap violations in 60 traces (`score.txt`) |
| E8 at most 25 new packages | 0 | 21 | **38: fails** | Venv closure per group (`variants/*/NOTES.md`) |

`langgraph` is dropped. Its numbers are kept below for reference only.

## 2. Scores (spec section 4)

Raw values; normalised over the variants that pass section 3 (`plain`, `pydanticai`) with `common/scoring.py` (`normalise`, best = 10). Where a measure has two parts (S2, S4) the two normalised parts are averaged.

| Id (weight) | plain | pydanticai | langgraph (excluded) | Score plain / pydanticai |
| --- | --- | --- | --- | --- |
| S1 orchestration lines (25) | 135 | 162 | 187 | 10 / 0 |
| S2 new packages, MB (20) | 0, 0 | 21, 27.9 | 38, 44.5 | 10 / 0 |
| S3 test glue lines (15) | 69 | 69 | 69 (80 incl. conftest) | 10 / 10 |
| S4 overhead s per variant (sum of 20 runs), import s (10) | 336.5, 0.03 | 344.5, 2.91 | 305.7, 3.56 | 10 / 0 |
| S5 framework concepts (10) | 0 | 9 classes | 7 | 10 / 0 |
| S6 breaking releases in 6 months (10) | 0 | 1 (2.0.0 on 2026-06-23; 112 releases since 2026-05-04) | 0 (22 releases) | 10 / 0 |
| S7 lines to map pause/resume to ADR-018 (10) | ~16 | ~16 | more (checkpoint thread) | 10 / 10 |
| **Total** | | | | **10.0 / 2.5** |

S6 from the PyPI release history (major version bumps; PydanticAI follows semver since 1.0). S7 sketch: both file-based variants map the pause the same way. `pause()` calls `approvals.queue(...)` with `job="flows"`, `operation="resume"`, `input={"run_id": ...}` and tier T2 instead of writing `awaiting_approval.json` (about 6 lines). `lfmap approvals approve <id>` then runs a small `flows.resume` operation that calls `resume(run_id, approve=True)` (about 10 lines). LangGraph would also need to tie the proposal to the checkpoint `thread_id` and to check `get_state().next`.

Decision rule (spec section 5): `pydanticai` is 7.5 points *below* `plain`, and its S1 is 20 % *more* lines; it provides no capability that `plain` needed more than 150 lines to build. Pause/resume, retries and batch phases take 135 lines in total in `plain`. `decide()` returns `plain`. Even if E8 were waived, `langgraph` would lose on S1, S2, S5 and import time; it is better only on run overhead (about 31 s over 20 runs, noise next to 21.5 h of Leading model time).

What the frameworks did not give: PydanticAI's `Agent` adds a message-format layer over our `ChatModel` and no durable pause (state is our own `state.json`, as in `plain`). LangGraph gives a real checkpointed interrupt, but it costs 38 packages, a pause/approval node split forced by `interrupt` re-running its node, and `model_validate`/`model_dump` glue in every node.

## 3. Shadow mode (spec section 6)

### Method

Claude reviewed every case diff against its card before opening any `reports.json`: the 7 base diffs (K4/K6/K7 clean and real, K5-red) in full, and each seeded copy as its change from the clean or real base. Limits of this measure:

- The answer key (`cases/README.md`, `expected.json`) was visible to this session, so Claude's own seed catch is not a blind measure. Claude's review serves only as the reference verdict and as the judge of whether each Leading finding is true.
- Claude's verdicts equal `expected.json` on all 19 cases. On K5-red Claude would escalate: 9 of 11 tests fail, the split helpers are dead code, and the design is wrong, so a Working retry will not fix it.

The three variants send the same prompts to the same model at temperature 0. Their first reviews are nearly identical, so the review quality below is a property of the Leading model and the card, not of the framework.

### Replay cases (19 per variant, first review)

| Measure | plain | pydanticai | langgraph | Threshold |
| --- | --- | --- | --- | --- |
| Seeds caught (12) | 9 (75 %) | 9 (75 %) | 9 (75 %) | ≥ 80 %: **missed** |
| Seeds the gates do not see (6) | 3 (50 %) | 3 | 3 | none |
| Findings dropped by the quote check, per 10 reviews | 0.5 | 1.5 | 2.1 | ≤ 1 |
| ... of which in first reviews | 0 | 0 | 0 | |
| First findings Claude judges false (quote real, claim wrong) | 7 | 6 | 6 | none |
| First verdict = Claude's | 15/19 | 14/19 | 14/19 | reported |

- **Seeds missed, in all three variants:**
  - `K4-clean-seed-exists`: `path.is_file()` before the permission check. This is a security-rule seed.
  - `K4-clean-seed-swallow`: `except OSError: pass` on the sidecar write.
  - `K7-clean-seed-count`: missing vector-count check. Verdict `ready`.
  - The seeds caught are mostly ones a red gate already pointed at. Of the 6 gate-invisible seeds only `order`, `unlink` and `sql` were caught.
- **Over-rejection:** all three clean reference modules got `rework`.
  - K4-clean: the reason is the false claim below.
  - K6-clean: the error message is "Search query is empty" instead of the card's "Query is empty". This is true, but the tests check only the code, so it is a nit and not a reason for rework.
  - K7-clean: `if not texts: return []` before `require_network()`. The card text is ambiguous here.
- **False findings with real quotes,** which the quote check cannot catch:
  - In every K4 case the Leading model claims `"reason_code" in e.details` raises `TypeError` because `details` defaults to `None`. `ToolError.__init__` stores `details or {}`, and `test_other_tool_error_is_raised` passes in the gate log the model had in front of it.
  - In `plain` K7-real it claims `ip_address(None)` raises an uncaught `TypeError`; it raises `ValueError`, which is caught. As a result K7-real got `rework` in `plain` for a wrong reason, and `ready` in the other two variants. Both are wrong: the real defects are the missing count check and the unhandled `ValueError` from bad JSON.
  - Cause: the card shows `ToolError(code, message, details=None)` and not the normalisation. Cards should state the real contract of the types they use.
- **K4-real:** the Leading model caught the hand-made `.tmp.json` temp file. It missed the newline translation on Windows: `read_text()` and `os.fdopen()` without `newline=""` change `\r\n`, so chunk offsets drift.
- **Empty replies:** 2 of 122 Leading calls returned nothing after about 2000 s (`invalid_json`). Median Leading call: 531 s; total Leading time 21.5 h against 1.5 h for the Working model.

### Plan run (package K4-K7, one per variant)

Claude would accept **0 of 4** Plan cards as written (threshold ≥ 70 %), in all three variants:

- every card has `tests: []` although the package names the test file of each module;
- `scope` is empty;
- the K4 prompt tells the Worker to import `ExtractResult` and `SkipResult` from `lfmap_core`, where they do not exist.

With no tests on the cards the harness never ran the pytest gate, and `ruff` failed on every attempt. The Leading model still returned `ready` for K4, K6 and K7 (and `escalate` for K5 after an `invalid_json` review). It explained the red lint as "pre-existing" or "style only". It also reviewed round 2 as a delta against round 1 and called it "purely cosmetic".

Claude re-applied the final attempts of the `plain` run at `018ffdf` on Linux:
- `test_extract.py`, `test_fts.py` and `test_embed.py` fail at import (wrong `lfmap_core` import, `from typing import list`, no `BATCH_SIZE`);
- `test_chunker.py` has 6 of 11 failing.

Approving this run, as the F4 script did mechanically, would have merged four broken modules.

### Characters Claude would read

Reports plus the diffs of `ready` cards were 22–25 % of the characters of all attempts (plain 49 k vs 230 k). This saving is not real while `ready` can be wrong, as in the Plan run and on K7-clean-seed-count.

### Harness defects found (fix before the next shadow run)

1. A Plan card with no `tests` must be refused by the harness (or fall back to the package's test list), never sent to Work. Otherwise the pytest gate silently disappears.
2. The diff of round 2 and later must be against the base, not against the previous round, so the reviewer sees the whole module.
3. Show the reviewer which gates are red with a fixed rule ("any red gate means not ready"), or decide `ready` only when every gate is green, without asking the model.
4. Cards should state the real contract of imported types (for example, `ToolError.details` is always a dict).
5. Minor: `normalise` returns `-0.0` for the worst variant.

## 4. Conclusions

1. Phase 2 orchestration starts from `spikes/2a1-framework/variants/plain` + `common/`: standard library + pydantic, file state per run. Move it into a package when 2a.2 (Agent Router) needs it.
2. Revisit a framework only on a named trigger: a need for durable multi-step graphs with branches across process restarts that grows `plain` past 150 lines for that capability (the section 5 rule), or multi-machine execution.
3. ADR-022 stays Proposed. The local Leading model may keep running in shadow mode after the harness fixes above, but filter mode is not in sight:
   - the seed catch is below threshold;
   - it gives false findings with real quotes;
   - it rejects clean code;
   - it approves code that fails gates.

   The deterministic gates did the useful work. The cheapest win is to make them decide `ready`/`rework` and keep the model for findings only.
4. Thinking-on `qwen3.8:27b` costs about 9 min per review on this GPU; a package of four cards takes about 45 min. That is acceptable for overnight batches only.

## Draft ADR-024: orchestration framework for Phase 2 (result of spike 2a.1)

- Status: Proposed (gate:po, owner decides)
- Date: 2026-11-04
- Amends: ADR-004. Related: ADR-021 (build in-house first), ADR-022 (local Leading Agent, Proposed), ADR-018 (approvals).

**Context.** ADR-004 said: at the start of Phase 2, spike PydanticAI and LangGraph on one Planner → Worker → Reviewer flow, then pick one. Spike 2a.1 built the same flow three times (plain Python, PydanticAI 2.60, LangGraph 1.2.16) on shared framework-free code. It ran each 20 times on DIEP-ANH with local models and scored them with the pre-registered rules of `docs/specs/framework-spike.md`.

**Decision.**
1. No agent framework for now. The Phase 2 orchestration uses the plain Python variant (standard library + pydantic, state in one JSON file per run, the pause as a file plus `resume` in a new process).
2. ADR-004 is amended from "pick one" to "pick one or none". The choice is re-opened only when a capability needed by LFMAP would take more than 150 lines to build in plain code, or when execution must span several machines.
3. The approval pause maps to the ADR-018 approvals queue as a proposal (`flows.resume`, T2); no framework checkpoint store.

**Reasons.**
- LangGraph fails the dependency limit: 38 packages, 44.5 MB.
- PydanticAI passes every exclusion criterion but scores 2.5 against 10.0: more code (162 vs 135 lines), 21 packages, 9 concepts to learn, a major release in the last 6 months, and import time 2.9 s vs 0.03 s. It gives no durable pause.
- No framework changed review quality: all three ran the same prompts with the same results.

**Consequences.**
- No new runtime dependency.
- The orchestration code is owned and must be maintained in-house, about 135 lines today.
- The spike's `common/` (models, gates, quote check, socket guard) is the seed of the 2a.2 Agent Router work.
- The harness defects in section 3 are fixed before any further shadow run.
- ADR-022 progress note: shadow measures missed the thresholds (75 % seeds, false findings, 0/4 Plan cards), so it stays Proposed.
