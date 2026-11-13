# Handoff addendum: start card for JF-1 (jobs into Flows, stage 1: R2 and R4)

Issue: JF-1 [#231](https://github.com/hungnp1999/lfmap/issues/231). Analysis: [docs/research/2026-11-10-jobs-into-flows-risk-analysis.md](../research/2026-11-10-jobs-into-flows-risk-analysis.md) (R2, R4; PR #230; umbrella #227). Spec: [docs/specs/flows.md](../specs/flows.md) sections 9 and 13. ADR-018 and ADR-024 (notes of 2026-11-10). Card format follows [2026-11-13-web-4-start-card.md](2026-11-13-web-4-start-card.md).

## Task card

- Task: JF-1, a job edited while it waits for approval must not block itself (R2); `lfmap jobs doctor` fails on anything the runner refuses at load (R4). Roadmap: Phase 2, "Gộp jobs vào Flows".
- Labels: `exec:CC`, `P1`, `security-review`.
- Executor: Claude Code, Cloud, **Sonnet**. One PR, draft, `Closes #231` and `Refs #227`.
- Blocked by: none. Not blocked by decisions D1 to D3 of #227 (all taken by the owner on 2026-11-10).
- Size: small to medium (two source files, one message in `cli.py`, new tests, three docs).
- Resource: none (Cloud, offline). 7 `test_jobs_doctor` failures on Linux are the known baseline; compare, do not "fix" them.
- Must land before the `email` plugin.

## Session protocol (standing rule of the owner, 2026-11-13)

1. Open the **draft PR at your first commit** (title `fix(jobs): a paused job edited in jobs.toml starts a new run; doctor checks the runner's load (JF-1)`, body from the PR template, `Closes #231`, `Refs #227`), so the reviewing thread can subscribe to it from the start. Keep it a draft until CI is green.
2. Post your **final report as a PR comment whose first line is `DONE`**, followed by: what changed, test results (including the Linux baseline failures), `flows_run.py` line count by the section 9 measure, `/security-review` findings and your answers, open questions. Post it only when the work is complete and CI on the head commit is green or you state exactly why it is not. Do not post `DONE` earlier.
3. Do not merge. The reviewing thread starts the review when it sees `DONE` with green CI.

## Decisions already taken (do not reopen)

- Owner, 2026-11-10: D1 (retire the request-over-bus path later, JF-2/JF-4), D2 (`jobs.toml` frozen, no new job feature), D3 (`flows_run.py` cap rises to 280 only for retention, stale runs and superseded waiting run, in stage JF-3, **not** in this task). JF-1 works under the **current cap of 230 lines**.
- R2 fix (analysis): a waiting run whose hash no longer matches is closed as `expired` together with its proposal (`approvals` move to `expired`), then the new run starts. Use `flows_run.close(proposal, "expired")` and the approvals module's existing move; do not add a state or change the run file format.
- R4 fix (analysis): doctor runs the same load as the runner and fails with the runner's message. The "optional hardening" of R4 (a job start skipping `flows.toml`) is **out of scope**.
- No new dependency, no state format change.

## File scope (required)

May change or create:

- `packages/lfmap-core/src/lfmap_core/jobs_flow.py` (R2: compare the waiting run's `flow_sha256` with the current translation hash in `run_job`)
- `packages/lfmap-core/src/lfmap_core/jobs_doctor.py` (R4: a check that performs the runner's load)
- `packages/lfmap-core/src/lfmap_core/cli.py` (the message of `approvals approve` for a changed flow only: it names `lfmap approvals reject <id>`)
- `packages/lfmap-core/tests/` (new test functions or new files; the frozen files below are not edited)
- `docs/jobs.md` (run `lfmap flows check` after editing either file), `docs/specs/flows.md` section 13 (one or two lines on R2), `changelog.d/231-jobs-paused-edit.fixed.md` (check `changelog.d/README.md` for the category suffix)

Must not touch: `approval.py`, `approvals.py` beyond calling existing functions, `events_adapter.py`, `flows_run.py` beyond what fits under the 230-line cap (it is at 293 lines by raw `wc -l`; use the **section 9 measure**, which counts what spec section 9 says, and show the number in the PR). If the fix does not fit outside `flows_run.py`, stop and report on #231. ADR files, `.claude/`, adapters.

## Steps

1. Read the R2 and R4 sections of the analysis, `jobs_flow.run_job` and `extend`, `flows_run._flows_file`, `check_resume`, `close`, and `jobs_doctor._load` and `run_checks`. Read the existing `test_jobs_flow.py` fixtures.
2. Tests first (new functions or a new file such as `test_jobs_flow_edit.py` and `test_jobs_doctor_load.py`), see them fail for the right reason:
   - R2, three cases: a job paused at `max_tier = 0`, then `jobs.toml` edited by (a) changing the input, (b) removing the job and adding it again with a different step, (c) disabling and enabling it with a changed input. Expected for each: the next `jobs run` closes the old waiting run as `expired`, its proposal is in `expired`, and a new run starts with a new proposal id. Today it answers `Queued for approval` with the old id and `approvals approve` refuses `flow changed; start a new run`.
   - R2 control: the waiting run with an **unchanged** job still answers `Queued for approval` with the same id (existing behaviour).
   - `approvals approve` on a changed flow: the message names `lfmap approvals reject <id>` with the real id.
   - R4: doctor fails on a broken `flows.toml` (TOML error, shape error, non-UTF-8) and on a job and a flow with the same id; the failure text is the runner's message. A valid pair passes.
3. R2 fix in `jobs_flow.run_job`: when the newest run is `awaiting_approval`, compute the current translation hash and compare it with `flow_sha256`; equal keeps today's refusal, different closes run and proposal as `expired` and carries on to `flows_run.start`.
4. `approvals approve` message (cli.py) for the changed-flow refusal.
5. R4: doctor performs the same load as the runner (`flows.toml` parse, translation, id clash) by calling the runner's own loader, not a copy, and reports its message. Add it as one check in `run_checks`; keep existing check names stable.
6. Docs and changelog fragment.
7. Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`. Merge origin/main again before push.
8. Open the draft PR at the first commit, then run `/security-review` on the diff (approvals path) and answer every finding in the PR.

## Frozen tests (must pass without edits)

`packages/lfmap-core/tests/test_jobs_flow.py`, `test_flows_run.py`, `test_approvals.py`. Hand-write expected values; do not derive them from the code under test. All tests offline.

## Completion criteria

- [ ] The three R2 edit cases pass, plus the unchanged-job control and the approve message test
- [ ] Doctor fails on anything `flows_run.start` would refuse at load (broken `flows.toml`, id clash), with the runner's message
- [ ] `flows_run.py` stays at or under 230 lines by the section 9 measure (number shown in the PR); no change outside the file scope
- [ ] `/security-review` run and every finding answered in the PR
- [ ] Changelog fragment present; CodeQL and tests green
- [ ] Draft PR opened at the first commit; final report posted as a PR comment starting `DONE`

## Start prompt (paste into a new Claude Code Cloud session, model Sonnet, repo lfmap)

```
Task JF-1 of lfmap #231 (jobs into Flows, stage 1): fix R2 and R4 of docs/research/2026-11-10-jobs-into-flows-risk-analysis.md. Read docs/handoff/2026-11-14-jf-1-start-card.md first, then the R2 and R4 sections of the analysis, docs/specs/flows.md sections 9 and 13, and packages/lfmap-core/src/lfmap_core/jobs_flow.py, flows_run.py (start, _flows_file, check_resume, close), jobs_doctor.py (_load, run_checks), and tests/test_jobs_flow.py. Branch from up-to-date main; merge origin/main again before push.

File scope: jobs_flow.py, jobs_doctor.py, the "flow changed" message of `approvals approve` in cli.py, new tests under packages/lfmap-core/tests/, docs/jobs.md, docs/specs/flows.md section 13, changelog.d/231-jobs-paused-edit.fixed.md. Do not touch approval.py, events_adapter.py, ADRs, .claude/, adapters. Do not edit test_jobs_flow.py, test_flows_run.py, test_approvals.py. flows_run.py must stay at or under 230 lines by the spec section 9 measure; if the fix does not fit outside it, stop and report on issue #231.

Tests first (new functions/files): R2 for three edits of a job paused at max_tier = 0 (input changed; job removed then added again; job disabled then enabled): the next `jobs run` closes the old waiting run as expired, its proposal moves to expired, a new run starts with a new proposal id. Control: unchanged job still answers "Queued for approval" with the same id. `approvals approve` on a changed flow names `lfmap approvals reject <id>`. R4: `lfmap jobs doctor` fails with the runner's own message on a broken flows.toml (TOML error, shape error, non-UTF-8) and on a job and flow with the same id; call the runner's loader, do not copy it. Hand-write expected values; all tests offline.

Fix: in jobs_flow.run_job, when the newest run is awaiting_approval compare its flow_sha256 with the current translation hash; if different, close run and proposal as expired (existing flows_run.close and approvals move), then start the new run. No state format change, no new dependency, no new job feature, out of scope: skipping flows.toml at job start.

Run uv run pytest, uv run ruff check . and uv run ruff format --check . (7 test_jobs_doctor failures on Linux are pre-existing). Commit trailers: Dev-Environment: cloud and Claude-Session (add Dev-Environment by hand if the hook does not). Open the draft PR at your FIRST commit (template, "Closes #231", "Refs #227"). Then run /security-review on the diff and answer every finding in the PR. When complete and CI is green, post your final report as a PR comment whose first line is exactly DONE (what changed, test results, flows_run.py line count by the section 9 measure, security-review answers, open questions). Do not post DONE earlier. Do not merge.
```

## Review checklist for the thread (after the PR)

- Only files in the scope list changed; `flows_run.py` within the cap by the section 9 measure (or untouched); `uv.lock` untouched.
- R2: comparison uses the current translation hash; expired run and proposal are consistent (no waiting run without a pending proposal, no pending proposal for an expired run); unchanged job keeps the old behaviour; no path lets an approval for the old flow run the new flow.
- Approve message names `approvals reject` with the id; nothing else in `cli.py` changed.
- R4: doctor calls the runner's loader; failure text is the runner's; existing doctor checks and names unchanged.
- Frozen test files unedited; new tests cover the listed cases; CodeQL green; `/security-review` answered.
- Verdict: Approve / Approve with changes / Reject. Merge (squash, lfmap rule) only when not draft and checks green.
