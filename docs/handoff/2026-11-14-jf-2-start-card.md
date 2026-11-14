# Handoff addendum: start card for JF-2 (jobs into Flows, stage 2: stop producing operation requests)

Issue: JF-2 [#239](https://github.com/hungnp1999/lfmap/issues/239). Analysis: [docs/research/2026-11-10-jobs-into-flows-risk-analysis.md](../research/2026-11-10-jobs-into-flows-risk-analysis.md) (R1, R8, decision D1 option B, stage JF-2; PR #230; umbrella #227). Spec: [docs/specs/flows.md](../specs/flows.md) section 13. ADR-018 and ADR-024 (notes of 2026-11-10). Card format follows [2026-11-14-jf-1-start-card.md](2026-11-14-jf-1-start-card.md). JF-1 (#231) is merged (PR #329), so `jobs_flow.py` and `jobs_doctor.py` already carry its changes: read them as they are on `main`.

## Task card

- Task: JF-2, nothing produces `<plugin>.<operation>.requested` any more. A job with `via = "event"` runs as a plain call; `Step.via` and the request-over-bus call are removed. Roadmap: Phase 2, "Gộp jobs vào Flows".
- Labels: `exec:CC`, `P1`.
- Executor: Claude Code, Cloud, **Sonnet**. One PR, draft, `Closes #239` and `Refs #227`.
- Blocked by: none. D1 (option B) was taken by the owner on 2026-11-10.
- Size: small to medium (four source files, one rewritten test file, three docs).
- Resource: none (Cloud, offline). 7 `test_jobs_doctor` failures on Linux are the known baseline; compare, do not "fix" them.
- Must land before the `email` plugin.

## Session protocol (standing rule of the owner, 2026-11-13)

1. Open the **draft PR at your first commit** (title `refactor(jobs): stop producing operation requests over the bus; via = "event" runs as a call (JF-2)`, body from `.github/pull_request_template.md`, `Closes #239`, `Refs #227`), so the reviewing thread can subscribe to it from the start. Keep it a draft until CI is green.
2. Post your **final report as a PR comment whose first line is `DONE`**, followed by: what changed, test results (including the Linux baseline failures), grep result for `.requested` producers, open questions. Post it only when the work is complete and CI on the head commit is green or you state exactly why it is not. Do not post `DONE` earlier.
3. Do not merge. The reviewing thread starts the review when it sees `DONE` with green CI.

## Decisions already taken (do not reopen)

- D1-B (owner, 2026-11-10): the request-over-bus path is retired in two stages. JF-2 stops the **producers**; JF-4 (#241) removes the adapter's receiving side, channel `event`, `[events] max_tier`, the plain-call approve path and #219, with Plugin Contract v0.3. Do not start JF-4 work here.
- `via = "event"` stays valid in `jobs.toml` (old files must load and run) and is read as `"call"`; `lfmap jobs doctor` warns and names the job. In `flows.toml` the key is simply unknown, so a step with `via` is a load error.
- D2: `jobs.toml` is frozen (no new job feature). D3: `flows_run.py` is not touched here.
- No new dependency, no state format change.

## File scope (required)

May change or create:

- `packages/lfmap-core/src/lfmap_core/jobs.py`, `jobs_flow.py`, `flows.py`, `jobs_doctor.py`
- `packages/lfmap-core/tests/` (rewrite `test_jobs_via_event.py`; fix other tests only where they used `via` on a step, such as `test_plugin_compat.py`, and say so in the PR)
- `docs/jobs.md`, `docs/events.md`, `docs/specs/flows.md` (section 13), `changelog.d/239-jobs-stop-requests.changed.md`

Must not touch: `events_adapter.py` (it still receives `.requested`; removal is JF-4), `approvals.py`, `approval.py`, the plain-call branch of `approvals approve`, `flows_run.py`, ADR files, `.claude/`, adapters, Plugin Contract.

## Steps

1. Read the R1 and R8 sections and decision D1 of the analysis; `jobs.py` (`Job.via`, `check_via`), `jobs_flow.py` (`translate`, `call`, `EVENT_DRAIN`, `run_job`), `flows.py` (`Step.via`, the check near line 179, the `.requested` trigger check near line 196), `jobs_doctor.py` (the `check_via` use), and the current `test_jobs_via_event.py`.
2. Tests first (rewrite `test_jobs_via_event.py`; see them fail for the right reason):
   - An event job (`via = "event"` in `jobs.toml`, plugin with `[adapters] events = true`) runs as a **direct call**: the operation executes, **one** audit line is written (channel `flow`), no `.requested` event is published (check the bus).
   - It obeys only the job's `max_tier`; a job above its `max_tier` pauses behind a `flows.resume` proposal.
   - The R1 case (flow ceiling 1, `[events] max_tier = 0`) now runs; the old blocked-for-good state cannot occur.
   - `lfmap jobs doctor` warns for a job with `via = "event"` and names the job; a job without `via` has no warning. The job still loads and runs.
   - `flows.toml` with `via` on a step fails to load (unknown field), message names the field.
3. `jobs.py`: keep `Job.via` accepted as `"call"` or `"event"` but treat both as a call; drop the `events = false` refusal in `check_via` (a job with `via = "event"` on a plugin without events is now just a call). Keep a way for doctor to know the key was set.
4. `jobs_flow.py`: remove `EVENT_DRAIN`, its set/reset in `run_job`, the `via` argument of the translated `Step`, and the `request_operation` call in `call`. `flows.py`: remove `Step.via` and the check that depends on it. Keep the guard that ignores `*.requested` triggers (`flows_triggers.py`) and the trigger check at `flows.py:196`: they protect against old queue entries until JF-4.
5. `jobs_doctor.py`: replace the `via` failure with a warning naming the job ("`via` is deprecated and ignored, the job runs as a call").
6. Docs: `docs/jobs.md` `via = "event"` section says the key is deprecated and ignored; `docs/events.md` says core no longer publishes `.requested` (the adapter still receives it until JF-4); `docs/specs/flows.md` section 13 gets one or two lines. Run `lfmap flows check` after editing docs that contain flows. Changelog fragment (`uv run python scripts/changelog_fragments.py check`).
7. Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`. Merge origin/main again before push.
8. Final grep: `grep -rn "\.requested\|request_operation\|EVENT_DRAIN" packages/lfmap-core/src` must show only the receiving side in `events_adapter.py` and the ignore guards; paste the output in the DONE comment.

## Frozen tests (must pass without edits)

`packages/lfmap-core/tests/test_jobs_flow.py` (if a line there must change because `Step.via` is gone, stop and report on #239 instead of editing it) and `test_flows_run.py`. Hand-write expected values; do not derive them from the code under test. All tests offline.

## Completion criteria

- [ ] No code path outside tests publishes a `.requested` topic (grep shown in the PR)
- [ ] An old `jobs.toml` with `via = "event"` loads and runs as a call; doctor warns and names the job
- [ ] `Step.via`, `EVENT_DRAIN` and the request call in `jobs_flow.call` are gone; `flows.toml` with `via` is a load error
- [ ] The R1 case runs; one audit line per run
- [ ] No change outside the file scope; frozen tests unedited
- [ ] Changelog fragment present; CodeQL and tests green
- [ ] Draft PR opened at the first commit; final report posted as a PR comment starting `DONE`
- [ ] `/security-review` is not required (scope does not touch adapters or `cli.py`); run it if you end up touching either

## Start prompt (paste into a new Claude Code Cloud session, model Sonnet, repo lfmap)

```
Task JF-2 of lfmap #239 (jobs into Flows, stage 2): stop producing operation requests over the bus (decision D1-B of docs/research/2026-11-10-jobs-into-flows-risk-analysis.md, removes R1 and R8). Read docs/handoff/2026-11-14-jf-2-start-card.md first, then the R1, R8 and D1 sections of the analysis, docs/specs/flows.md section 13, and packages/lfmap-core/src/lfmap_core/jobs.py (Job.via, check_via), jobs_flow.py, flows.py (Step.via and the checks near lines 179 and 196), jobs_doctor.py, and tests/test_jobs_via_event.py. JF-1 is already merged: read the files as they are on main. Branch from up-to-date main; merge origin/main again before push.

File scope: jobs.py, jobs_flow.py, flows.py, jobs_doctor.py, tests under packages/lfmap-core/tests/, docs/jobs.md, docs/events.md, docs/specs/flows.md section 13, changelog.d/239-jobs-stop-requests.changed.md. Do not touch events_adapter.py, approvals.py, approval.py, the plain-call branch of `approvals approve`, flows_run.py, ADRs, .claude/, adapters, Plugin Contract: removing the receiving side is JF-4 (#241). Do not edit test_jobs_flow.py or test_flows_run.py; if one must change, stop and report on issue #239.

Tests first (rewrite test_jobs_via_event.py): a job with via = "event" runs as a direct call, writes one audit line (channel flow), publishes no .requested event, obeys only the job's max_tier and pauses behind a flows.resume proposal; the R1 case (flow ceiling 1, [events] max_tier = 0) now runs; `lfmap jobs doctor` warns and names the job with via = "event" (job still loads and runs); flows.toml with via on a step fails to load as an unknown field. Hand-write expected values; all tests offline.

Change: Job.via stays accepted and is read as "call"; drop the events = false refusal; remove Step.via, EVENT_DRAIN (and its set/reset in run_job) and the request_operation call in jobs_flow.call; keep the guards that ignore *.requested triggers. Doctor turns the via failure into a warning. Update the three docs and add the changelog fragment. No new dependency, no state format change, no new job feature.

Run uv run pytest, uv run ruff check . and uv run ruff format --check . (7 test_jobs_doctor failures on Linux are pre-existing). End with `grep -rn "\.requested\|request_operation\|EVENT_DRAIN" packages/lfmap-core/src` and paste it in the report. Commit trailers: Dev-Environment: cloud and Claude-Session (add Dev-Environment by hand if the hook does not). Open the draft PR at your FIRST commit (template, "Closes #239", "Refs #227"). When complete and CI is green, post your final report as a PR comment whose first line is exactly DONE (what changed, test results, grep output, open questions). Do not post DONE earlier. Do not merge.
```

## Review checklist for the thread (after the PR)

- Only files in the scope list changed; `events_adapter.py`, approvals modules and `flows_run.py` untouched; `uv.lock` untouched.
- Grep shows no producer of `.requested`; the receiving side and ignore guards remain.
- Old `jobs.toml` with `via = "event"` loads and runs; doctor warns by job id; `flows.toml` `via` is a clear load error.
- One audit line per run, channel `flow`; only the job's `max_tier` applies; pause uses `flows.resume`.
- No leftover `EVENT_DRAIN` context var or unused imports; docs say deprecated and ignored.
- Frozen tests unedited; CodeQL green.
- Verdict: Approve / Approve with changes / Reject. Merge (squash, lfmap rule) only when not draft and checks green.
