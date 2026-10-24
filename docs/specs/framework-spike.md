# Spec: Phase 2a.1 agent framework spike

- Version 0.1, 2026-10-24 · Author: Claude (Managing Agent) · Handoff: [`docs/handoff/2026-10-24-phase2a-framework-spike.md`](../handoff/2026-10-24-phase2a-framework-spike.md)
- Decides: ADR-004 ("at the start of Phase 2, spike PydanticAI vs LangGraph on one Planner → Worker → Reviewer flow, then pick one"), read together with ADR-021 (build in-house first) and ADR-022 (Proposed: local Leading Agent, shadow mode first).
- This file is written **before** any spike code. Exclusion criteria, scores and the decision rule below may not be changed after the first real run; a change needs a new version of this file and a note in the result report.

## 1. Variants

| Id | Variant | Pinned packages (spike project only) | Licence |
| --- | --- | --- | --- |
| `plain` | Plain Python baseline: stdlib + `pydantic` (already a runtime dependency) + `urllib` to Ollama, state in a JSON file | none new | — |
| `pydanticai` | PydanticAI, slim install | `pydantic-ai-slim[openai]==2.60.0` (no `logfire`, no full `pydantic-ai`) | MIT (`openai` client Apache-2.0) |
| `langgraph` | LangGraph with SQLite checkpointer | `langgraph==1.2.16`, `langchain-ollama==1.1.0`, `langgraph-checkpoint-sqlite==3.1.2` | MIT |

Versions are the latest on PyPI on 2026-10-24. The `plain` baseline exists because ADR-021 puts in-house first: a framework is adopted only if it clearly beats it (§5).

## 2. The flow (identical for every variant)

One **work package** goes through four phases. Model calls go to a local Ollama at `127.0.0.1:11434` only.

1. **Plan** (Leading model): `package.toml` + `standard.md` → `list[Card]`. Replay mode skips this and loads the known cards, so the other phases can be compared on equal input.
2. **Work** (Working model): one completion per card → file written into a git worktree → deterministic gates. On gate failure, one more round with the gate output in the prompt (max 2 rounds per card).
3. **Review** (Leading model): diff + `standard.md` → `Report` (verdict `ready` | `rework` | `escalate`, findings with checklist id, file, quoted line). The quote check drops every finding whose quote is not in the diff and counts it as hallucinated. `rework` sends the card back to Work once; a second `rework` becomes `escalate`.
4. **Approve**: the run writes `awaiting_approval.json` (run id, cards, verdicts, report path), saves its state and **the process exits**. `run.py resume <run_id> --approve|--reject` in a new process loads the state and finishes (`done.json`). This stands in for the ADR-018 approvals queue without touching it.

Phases run **batch by batch** (all cards planned, then all worked, then all reviewed) so Ollama loads each model once per phase (research note `docs/research/2026-10-23-local-model-tiers.md` §5). Per-card interleaving is not allowed.

Shared, framework-free code (`common/`): data models (`Package`, `Card`, `Attempt`, `Report`, `Finding`), prompts, gates, quote check, Ollama model names, the socket guard, metrics. Variants only write the orchestration: how phases, branching, retries, state and the approval pause are expressed.

Gates (deterministic, never a model): frozen tests green (`pytest -q` on the card's test files), `ruff check` and `ruff format --check` on the written file, no file outside the card's scope touched, test files unchanged by SHA-256.

Models: Leading `qwen3.8:27b`, Working `qwen2.5-coder:14b`, temperature 0, `num_ctx` 16384, JSON schema output (`format`). Thinking setting as decided by B0b; if B0b has not run, model default.

## 3. Exclusion criteria (any failure removes the variant)

| Id | Criterion | How it is checked |
| --- | --- | --- |
| E1 | Every runtime package (transitive) of the variant is permissive (MIT, BSD, Apache-2.0, ISC, PSF, MPL-2.0 per ADR-015); no fair-code, AGPL, SSPL, BSL | `scripts/check_licenses.py` logic run on the spike venv |
| E2 | No connection to any host except `127.0.0.1`/`localhost` during a full run, with no extra environment variable set to disable telemetry | socket guard in `common/` (patches `socket.socket.connect`, records and fails on non-loopback) in the contract test and in the real run |
| E3 | Runs on Windows, Python 3.12, with Ollama; structured output works with both models | real run on DIEP-ANH |
| E4 | The approval pause survives a process exit: state on local disk, resume in a new process, no server or cloud service | contract test: run → exit → `resume` in a subprocess |
| E5 | Testable without a model: the variant accepts a fake model; the full contract test runs offline in under 30 s | contract test with `FakeModel` |
| E6 | Embeddable as one step: no own daemon, scheduler, web server or required platform account; a flow can be called as a function from a job or a future LFMAP Flows step | code review |
| E7 | Batch-phase order (§2) is expressible without fighting the framework | code review: no per-card model swaps in the trace |
| E8 | Adds at most 25 third-party runtime packages over the `plain` variant | `importlib.metadata` diff of the two venvs |

## 4. Scores (only for variants that pass §3)

| Id | Measure | Weight | Better is |
| --- | --- | --- | --- |
| S1 | Orchestration code lines (non-blank, non-comment) in the variant folder | 25 % | fewer |
| S2 | New runtime packages and their installed size (MB) | 20 % | fewer, smaller |
| S3 | Test ergonomics: lines of test glue needed for the contract test (fakes, fixtures) | 15 % | fewer |
| S4 | Framework overhead: wall time of a run minus time inside model calls; cold import time | 10 % | lower |
| S5 | Concepts to learn: framework classes and decorators used in the variant | 10 % | fewer |
| S6 | API churn: releases with breaking changes in the last 6 months (changelog) | 10 % | fewer |
| S7 | Fit with ADR-018 approvals and the future EventBus/Flows: lines needed to map the pause/resume to the approvals queue format (sketch, not code) | 10 % | fewer |

Each measure is normalised to 0–10 across the passing variants (best = 10). The report shows raw numbers next to the scores.

## 5. Decision rule

1. Drop every variant that fails §3.
2. A framework (`pydanticai` or `langgraph`) is chosen over `plain` only if **both**: its total score is at least 1.5 points higher, and S1 is at least 30 % fewer lines or it provides a capability that `plain` needed more than 150 lines to build (named in the report).
3. Otherwise the result is "no framework": the `plain` code becomes the base for the Phase 2 orchestration, and the result ADR amends ADR-004 ("pick one" becomes "pick one or none").
4. Between the two frameworks, the higher total score wins; a tie goes to fewer runtime packages.

## 6. Shadow-mode measures (ADR-022, recorded but not part of the framework score)

Claude reviews every case **before** reading the Leading report, then compares.

| Measure | Threshold for later filter mode |
| --- | --- |
| Seeded bugs caught by the Leading review (≥ 12 seeds) | ≥ 80 % |
| Hallucinated findings (dropped by the quote check) | ≤ 1 per 10 reviews |
| Verdicts that match Claude's | reported |
| Cards from the Plan phase that Claude would accept as written | ≥ 70 % |
| Characters Claude had to read: report + ready diffs vs. all attempts | reported (token-saving proxy) |

Meeting the thresholds does not switch on filter mode; that still needs ADR-022 Accepted.

## 7. Cases

From `docs/handoff/prep/2026-10-24-framework-spike/cases/` (B0 and B0b set, 15 cases): K4–K7 real qwen output with known verdicts (`expected.json`), clean reference versions of K4, K6 and K7, and eight seeded copies (K4 order/unlink, K6 fold/order/sql, K7 count/proxy/userinfo). Task F0 adds at least four more seeds to reach twelve, covering kinds not yet seeded: a caller path used before the permission check; a swallowed exception; a missing `ToolError` on bad input; a mutable default argument. Base commit for the worktree: the parent of the first K4–K7 test commit in PR #26 (`git log ae149fc`); qwen raw output is `cba8810`, Claude's review fixes `781ec55`.

## 8. Out of scope

The Agent Router (2a.2), EventBus (2a.3), any change under `packages/` or `plugins/`, calls to Claude or any paid API, the real approvals queue, fine-tuning, filter mode.
