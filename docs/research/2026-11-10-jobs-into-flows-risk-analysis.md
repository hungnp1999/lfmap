# Jobs into Flows: risk analysis after stage 1 and plan for the remaining merge

- Date: 2026-11-10. Role: Architect / Reviewer. Issue #227. Requested by Hùng (decision 3 of `docs/research/2026-11-08-architecture-review.md`: merge components with similar functions, with a risk analysis for approval).
- Scope: the jobs and Flows merge (review items C3 and K1) and an update of the consolidation scan (review section 7). Analysis only; no code is changed by this file, and no ADR. Anything that touches an ADR, the Plugin Contract or an earlier owner decision is marked **[needs Hùng]**.
- State analysed: `main` at `a6c72e1`. Stage 1 is already merged: #190, spec PR #210 (`docs/specs/flows.md` section 13), code PR #215, Windows smoke on pc-01 on 2026-11-10 (comment on #190).
- Method: reading `jobs.py`, `jobs_flow.py`, `flows.py`, `flows_run.py`, `flows_triggers.py`, `approvals.py`, `events_adapter.py`, `cli.py`, `scripts/Invoke-LfmapJob.ps1` and their specs. Two findings were confirmed by a throwaway test run in a Cloud checkout (marked **probe**; the test file was deleted, nothing is committed). The others are from reading (**read**) and should get a test when they are fixed.

## 1. Verdict

Stage 1 did what was asked and did it safely: `jobs.toml` is unchanged, task names and exit codes are unchanged, and a job now runs through the Flows runner. The merge is not finished, and the part that is left is where the risk is:

1. **One proposal kind is not true yet.** The event adapter still queues plain-call proposals, and a job with `via = "event"` that receives one stays blocked for good (R1). The planned removal of the "legacy" reader (#219) would delete a path that is still in use (R3).
2. **A paused job blocks itself after an edit** until a person rejects the proposal or it expires (R2).
3. **Jobs and flows now fail together**: a mistake in either config file stops both (R4).
4. **The single runner has no housekeeping** (run files are never pruned, an interrupted run stays `running`), which matters more now that all scheduled work goes through it (R5, R6).

None of these loses data or weakens the approval boundary. R1 to R3 can stop scheduled work without a clear signal, which is the failure a scheduler must not have. R1 needs a job with `via = "event"`, which only a plugin with `[adapters] events = true` accepts; since #226 that is the shipped plugin `llm`, so the path is reachable as soon as such a job is written (the `jobs.toml` on pc-01 was not read for this file). The cheap moment to fix them is now, before `email` and the acceptance scenarios (#191) put real jobs on this path.

Recommendation in one line: finish the merge by **removing the request-over-bus path** (`via = "event"`), which is the root of R1 and R3 and of the second ceiling, then give the runner its housekeeping, and retire `jobs.toml` at the end of Phase 2. Three decisions are needed (section 6).

## 2. Where the merge stands

| Part | Before #190 | Now | Still duplicated |
| --- | --- | --- | --- |
| Runner | `jobs.run_job` and `flows_run` | `flows_run` only; `jobs_flow.run_job` is an alias | No |
| Config | `jobs.toml`, `flows.toml` | Both; jobs translated on load | Yes: a scheduled one-step flow can be written in either file |
| Scheduled task | `\LFMAP\<id>` runs `jobs run` | Job: `\LFMAP\<id>` runs `jobs run`. Flow: `\LFMAP\flow-<id>` runs `flows start` | Yes: two names, two commands |
| Proposal | plain call, `flows.resume` | `flows.resume` for the flow gate; plain call from the event adapter and from proposals queued before #190 | Yes |
| Ceiling | job `max_tier`, flow `max_tier`, `[events] max_tier` | Flow `max_tier` (jobs included), `[events] max_tier` | Two instead of three |
| Audit channel | `job`, `event`, `flow` | `flow`, `event`; `job` only for old proposals | `job` is dead for new runs |
| Run state | none for jobs, one file per flow run | Job: a file only while paused. Flow: always | Different rule per origin (`jobs_flow.is_job` inside `flows_run._save`) |

## 3. Risk register

Severity: **H** = scheduled work stops with no clear signal, or the approval boundary changes. **M** = wrong or confusing behaviour with a workaround. **L** = maintenance cost.

### R1 (H, probe). A `via = "event"` job that gets a proposal from the event adapter is blocked for good

- Path: the flow gate allows the call (`max_tier = 1`), the event adapter stops it (`[events] max_tier = 0`, or a run-time escalation through `ctx.require_approval`) and queues a **plain-call** proposal (`events_adapter.py:167`, `JobApprover` without a proposer). The `.failed` answer carries that `approval_id`, so `flows_run.advance` marks the run `awaiting_approval` with the id of a proposal that is not a `flows.resume`.
- Probe: after the proposal is approved (moved to `done`), the run file still says `awaiting_approval`; the next `jobs run` answers `Queued for approval` with the id of the finished proposal, with nothing pending. Rejecting or letting it expire gives the same result, because `approvals.sweep` and `approvals reject` close a run only for a `flows.resume` proposal (`approvals.py:153`).
- Consequence: the job never runs again until someone deletes the run file by hand. The approved call itself ran once, outside the run.
- Reach: jobs with `via = "event"` only, and `flows.toml` steps with `via = "event"` (R8), on a plugin with `[adapters] events = true` (`llm` today).
- Fix: decision D1. Removing `via = "event"` removes the path; keeping it needs the adapter to hand the stop back to the flow gate.

### R2 (M, probe). A job edited while it waits for approval blocks itself

- Path: `jobs_flow.run_job` refuses to start while the newest run of the job is `awaiting_approval` (`jobs_flow.py:86`). The run is bound to the hash of the translated job. After `jobs.toml` changes (new input, or the job removed and re-added), `approvals approve` refuses with `flow changed; start a new run` (`flows_run.py:257`), but a new run cannot start.
- Consequence: the job is stopped until a person runs `approvals reject <id>` or the proposal expires (7 days by default, up to 30). Before #190 the edited job queued a new proposal on its next run and the old one expired alone.
- Fix (stage JF-1): a waiting run whose hash no longer matches is closed as `expired` together with its proposal, then the new run starts. Message on `approve` names `approvals reject` meanwhile.

### R3 (M, read). #219 would delete a path that is still in use

- The reader that #219 calls legacy is the plain-call branch of `approvals approve` (`cli.py`, after the `is_flow_resume` test). It serves proposals queued before #190 **and** every proposal the event adapter queues today (R1 path, and any `.requested` event without a job id, queued under `events`).
- Consequence: deleting it "one release after #190" (owner decision 13.7 (3)) would leave event-adapter proposals that nobody can approve.
- Fix: #219 waits for D1. If the request path is removed (D1 option B), #219 becomes part of stage JF-4 and deletes both. If it is kept, the plain-call proposal is a permanent second kind and #219 is closed. Changing the timing of 13.7 (3) is **[needs Hùng]**.

### R4 (M, read). Jobs and flows share one failure domain

- `flows_run.start` reads and parses `flows.toml` and translates `jobs.toml` on every start (`_flows_file`, `flows_run.py:119`). A TOML error or a shape error in `flows.toml`, or a job and a flow with the same id, stops **every job**. A broken `jobs.toml` stops **every flow**, including event-triggered ones, whose events then retry and end as dead letters.
- Before #190 the two files were independent.
- Consequence: one typo while writing a new flow silently stops, for example, the nightly reindex. The log line in `jobs-YYYY-MM-DD.jsonl` shows exit 1, but nobody is told.
- Fix (JF-1): `lfmap jobs doctor` runs the same load as the runner and fails on it; `docs/jobs.md` says to run `lfmap flows check` after every edit. Optional hardening: a translated job needs only `jobs.toml`, so its start could skip `flows.toml` (the id clash is then reported by doctor and `register` only).

### R5 (M, read). Run files are never pruned and are all parsed on every job run

- There is no retention for `%LOCALAPPDATA%\lfmap\flows\runs\`. Jobs avoid files by decision 13.7 (1), but every scheduled or event flow run leaves one: an hourly flow gives about 8,760 files a year.
- `jobs_flow.run_job` calls `flows_run.list_runs(job_id, 1)`, which reads and validates every run file of every flow before each job run (`flows_run.py:94`); `flows list` does the same once per flow (`flows.py:123`).
- Consequence: slow growth of start time for every job, and a folder that no command cleans.
- Fix (JF-3): retention by count per flow for ended runs (never for `awaiting_approval`), applied by a TTY command and reported by doctor; the "is a run of this job waiting" test looks at pending proposals (which already carry the job id) instead of all run files.

### R6 (M, read). An interrupted run stays `running` and is never retried

- A process that is killed between two steps (power loss, Task Scheduler stop, sign-out) leaves the run file at `running`. For an event flow the redelivery finds the file and returns it as is (`flows_run.py:157`), so the bus marks the event done. Nothing lists or recovers such runs. A job leaves no file at all, so an interrupted job has only the missing line in the job log.
- This is Flows behaviour from before #190 (spec section 5: no retry). It is listed here because all scheduled work now depends on it.
- Fix (JF-3): doctor lists runs `running` for longer than a limit; a redelivered event whose run is stale marks it `failed` with reason `interrupted` instead of returning it. No automatic re-run of a step: a step may have had side effects, and re-running without a person would break the at-most-once behaviour that approvals rely on.

### R7 (M, read). The same scheduled work behaves differently by origin

| | Job (`jobs.toml`) | Scheduled flow (`flows.toml`) |
| --- | --- | --- |
| Task name | `\LFMAP\<id>` | `\LFMAP\flow-<id>` |
| Command | `jobs run <id>` | `flows start <id>` |
| Paused for approval | exit 1, `Queued for approval` | exit 0, status in the output (`cli.py:644` exits 1 only for `failed`) |
| Event bus after the run | drained (`drain_after_job`) | not drained |
| Run file | only while paused | always |

- Consequence: a monitoring rule on the exit code or the log reads the two differently; events published by a scheduled flow wait for the next job or `lfmap events run` (the FL-4 note "run `events run` once before the first event" is a symptom).
- Fix: one rule for both in JF-3 (drain after any scheduled run; one exit code for "paused"), and one origin in JF-5 (D2).

### R8 (L, read). `via` is accepted in `flows.toml` although it is meant for jobs only

- `Step.via` has no check that the step came from a job (`flows.py:68`). In a flow with several steps, an event step that is not answered within the drain fails the run with `timeout` while the request stays queued and runs at a later drain: a side effect after the run was marked failed, with no later step.
- Fix: D1 option B removes the field. Otherwise `check_flow` refuses it for declared flows (JF-1).

### R9 (L, read). No room left in the runner, and modules import each other in a circle

- `flows_run.py` is at 227 of 230 lines (ADR-024 note of 2026-11-06). R2, R5 and R6 all concern run state. Keeping them out of the file forces hooks such as `jobs_flow.is_job` inside `_save` and `propose`, which re-read `jobs.toml` on every save.
- `flows.py` imports `jobs` (for `Schedule`, `check_input`), `jobs_flow` imports `flows`, `flows_run` imports `jobs_flow`, and four places need a local import to break the circle.
- Fix: D3 for the cap; the shared pieces (`Schedule`, `check_input`, task commands) move to a neutral module when `jobs.toml` is retired (JF-5).

### R10 (L, read). Names that no longer say what they do

- New job runs are audited on channel `flow`; a reader that filters `audit.jsonl` on `job` sees nothing new. No script in the repository does (`scripts/` checked); reports written outside the repository were not checked.
- `[jobs] approval_ttl_days` sets the lifetime of flow proposals; `JobApprover`, `EventCall` and "job" in `approvals pending` name flow steps.
- Fix: rename at JF-5 with the old key read for one release; no action before.

### R11 (L). Rollback of stage 1 gets harder with time

- Reverting #215 restores the old runner. Runs of translated jobs paused under the new code would then be orphaned, although their `flows.resume` proposals can still be approved by the flows runner (spec 13.4). Each proposal lives at most 30 days, so the exposure is small and shrinking. No action; stated so that nobody plans on a late revert.

## 4. Options for the remaining merge

### D1. The request-over-bus path (`via = "event"`, `<plugin>.<operation>.requested`) **[needs Hùng]**

Today core can ask for an operation by publishing `.requested`; the event adapter runs it and answers `.completed` or `.failed`. The only producer is a job with `via = "event"`. An event-triggered flow with one call step now does the same thing (an event leads to an operation) through the flow gate, with one ceiling and a resumable pause.

| Option | What changes | Risk | Cost |
| --- | --- | --- | --- |
| A. Keep and repair | The adapter returns "needs approval" to the flow gate instead of queueing, so only `flows.resume` exists; run-time escalation inside the adapter needs the same hand-back; `check_flow` refuses `via` in declared flows | Two ceilings, two audit lines and the timeout case stay; the hand-back crosses the bus and is the hardest part to test | About 2 sessions, more code in two security-relevant modules |
| **B. Retire (recommended)** | Stage JF-2: `via = "event"` in `jobs.toml` is read as `"call"` with a doctor warning, `Step.via` is removed. Stage JF-4: the adapter's request handling, channel `event`, `[events] max_tier` and the plain-call proposal go; `[adapters] events = true` then means only "may publish". EventBus stays for facts and flow triggers | Plugin Contract v0.2 section 10 describes receiving `.requested`, so this is Contract v0.3 and a new frozen fixture; ADR-014 names the topic form (wording only). If several machines ever need remote calls (Team Edition), a request path is built again on the Protocol | About 1 session for JF-2, 1 to 2 for JF-4; removes about 150 lines and one channel from the security surface |
| C. Leave as is, document R1 | Nothing | R1 and R3 stay | None |

Recommendation: **B**. It removes the cause of R1, R3 and R8 instead of repairing each, leaves one ceiling and one proposal kind (the goal of decision 3), and shrinks the attack surface. JF-2 is safe at once because nothing produces requests afterwards; JF-4 waits for the acceptance scenarios so that no scenario turns out to need the path.

### D2. The future of `jobs.toml` **[needs Hùng]**

| Option | What changes | Risk | Cost |
| --- | --- | --- | --- |
| A. Keep for good as a short form | Nothing now. The translation layer (about 100 lines) and the per-origin rules of R7 stay | Two ways to write the same thing in docs, doctor and the later UI (#194) | Lowest now, permanent small cost |
| **B. Freeze now, retire at the end of Phase 2 (recommended)** | Now: no new job feature, docs point new work to `flows.toml`. At the end of Phase 2 (JF-5): `[runtime] root` moves to `config.toml` (old place read for one release), `lfmap jobs migrate` prints the equivalent `flows.toml` text for the owner to paste (no command writes config, as today), `register` creates `flow-<id>` and deletes `<id>`; `lfmap jobs register|doctor` stay as commands | Task rename needs one `register` at a TTY on pc-01; ADR-018 (2) says jobs are declared in `jobs.toml` (note needed); `jobs.toml` is also where ADR-023 put the runtime root | About 2 sessions plus one evening step for Hùng |
| C. Retire now | As B, immediately | Collides with #191 scenario work and `email`; no acceptance suite yet to prove the result | Same as B, worse timing |

Recommendation: **B**. Today there is one user and a handful of jobs at most, so migration costs almost nothing. After the installer (#201) and the first early users it has to be done on machines Hùng does not control. The end of Phase 2 is the last cheap moment and the acceptance suite exists by then.

### D3. The 230-line cap on `flows_run.py` **[needs Hùng]** (ADR-024 note of 2026-11-06)

| Option | What changes | Risk |
| --- | --- | --- |
| A. Keep 230 | R2, R5, R6 fixes live in other modules and reach in through hooks | Run-state logic spread over three files; more places like `is_job` inside `_save` |
| B. Split run state into `flows_state.py`, cap only the runner | Cleaner modules | Changes what the number measures; the spike's 135 lines included state, so the comparison in the ADR note no longer holds unless the sum is reported |
| **C. Raise the cap to 280 with named reasons (recommended)** | One file, one number. The 50 lines are reserved for retention, stale-run handling and the superseded waiting run; anything else still stops and reports | The cap moves a second time; the reasons must be written in the ADR note so that it does not drift |

Recommendation: **C**. The cap exists to trigger a framework review, and the note already says the next review is triggered by a named capability (parallel branches, loops, several machines), not by a line count. Housekeeping is none of these.

## 5. Migration plan

Each stage is one issue and one PR, tests written first, `Closes #N`. Order: JF-1 and JF-2 before `email`; JF-3 before the acceptance scenarios run on a schedule; JF-4 and JF-5 at the end of Phase 2.

| Stage | Content | Depends on | Tests (first) | Rollback | Env | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| JF-1 | R2: superseded waiting run is closed and a new run starts. R4: doctor fails on anything the runner's load would refuse; docs. R8 if D1 is not B | none | Edited, removed and disabled job while paused; broken `flows.toml` and id clash seen by doctor; existing `test_jobs_flow.py` unchanged | Revert the PR; no state format change | Cloud | `/security-review` (approvals path) |
| JF-2 | D1-B first half: `via = "event"` read as `"call"` with a doctor warning; `Step.via`, `EVENT_DRAIN` and the request call in `jobs_flow.call` removed; `docs/jobs.md`, `docs/events.md` | D1 | `test_jobs_via_event.py` rewritten: an event job runs as a call, one audit line, one ceiling; the R1 case can no longer occur | Revert the PR; `jobs.toml` files stay valid both ways | Cloud | none beyond CI |
| JF-3 | R5 retention, pending-proposal test in place of `list_runs`; R6 stale `running` runs; R7 drain after a scheduled flow and one exit code for "paused" (chosen in the spec PR) | D3 | Retention never touches a waiting run; stale run after a simulated kill; scheduled flow drains; exit codes golden test | Revert; pruned run files are ended runs only (kept in backups, #196) | Cloud, then pc-01 smoke with the script | Spec PR first, as for #190 |
| JF-4 | D1-B second half: remove the adapter's request handling, channel `event`, `[events] max_tier`, the plain-call approve path (#219 folded in); Plugin Contract v0.3 and fixture; `ARCHITECTURE.md` | JF-2, acceptance scenarios green (#191), no pending plain-call proposal on pc-01 | Frozen v0.2 fixture plugin still loads and publishes; a `.requested` event from an old queue ends as a dead letter with a clear reason | Revert; old proposals expire within 30 days either way | Cloud, pc-01 smoke | `gate:po` (Contract), `/security-review` (adapters) |
| JF-5 | D2-B: `[runtime]` in `config.toml`, `jobs migrate`, task rename, shared pieces to a neutral module, renames of R10; ADR-018 note | D2, JF-3 | `register --dry-run` golden for the rename; `migrate` output loads and passes `flows check`; old `[runtime]` place still read | Keep `jobs.toml` on disk; a revert plus `register` restores the old tasks | Cloud, then one evening step on pc-01 (Hùng runs `register` at a TTY) | `gate:po` (ADR-018 note) |

Scope warning: JF-1 to JF-3 are core hardening inside the Phase 2 item "Gộp jobs vào Flows" and add no Roadmap content. JF-4 changes the Plugin Contract one phase after v0.2 was frozen; that is the price of removing the path, and it is cheaper while `llm` is the only plugin with `[adapters] events = true`.

## 6. Decisions for Hùng

1. **D1**: retire the request-over-bus path (option B), in two stages, with #219 moved into the second stage? This changes the timing of decision 13.7 (3) and leads to Plugin Contract v0.3.
2. **D2**: freeze `jobs.toml` now and retire it at the end of Phase 2 (option B)?
3. **D3**: raise the `flows_run.py` cap to 280 lines for retention, stale-run handling and the superseded waiting run (option C)?

JF-1 needs no decision (bug fixes inside the accepted design) and can be scheduled now.

## 7. Consolidation scan, update of review section 7

| # | Overlap | State on 2026-11-10 | Next |
| --- | --- | --- | --- |
| K1 | Jobs and Flows | Stage 1 merged (#190). Remaining: this file | JF-1 to JF-5 |
| K2 | Model clients | `ModelClient` in core and plugin `llm` merged (#189, MC-1 to MC-3). `lfmap_knowledge/embed.py` still has its own client | MC-4 (vectors identical on pc-01), then MC-5; already tracked, no new decision |
| K3 | Diagnostics (`jobs doctor`, `flows check`, `events status`) | Open (#195) | R4 and R6 add doctor checks; do #195 together with JF-1 so the checks are written once |
| K4 | Event helper modules | Open (#195) | Unchanged; smaller after JF-4 (`events_names.py` loses the operation topics) |
| K5 | Durable state in three styles | Not now (owner, 2026-11-08) | R2 and R6 are consistency gaps between a run file and its proposal, the trigger named for K5. They are fixable without a store change, so the recommendation stays "not now"; revisit only if the acceptance suite shows a gap that file moves cannot close |
| K6 | Leading bench in two places | Done (project-files copy deleted 2026-11-08) | None |
| K7 | Conversion code in two repositories | Unchanged | None |
| K8 (new) | "Event leads to an operation" in two forms: `.requested` through the event adapter, and an event-triggered flow | Both live | D1 |
| K9 (new) | Ceilings: flow `max_tier` and `[events] max_tier` | Two | One after JF-4 |
| K10 (new) | Where to see what ran: `logs\jobs-*.jsonl`, `audit.jsonl`, `flows\runs\`, `events.db` | Four places, each with its own command | No storage merge (K5). One read-only view (`lfmap doctor` or the UI of #194) that joins them by run id and job id; low risk, after JF-3 |
| K11 (new) | Scheduled things of three kinds: job, scheduled flow, daily backup task (`[backup] daily`) | Three | Job and flow merge in JF-5. Backup stays apart on purpose: it is not a plugin operation and must run even when both config files are broken |

Not merged on purpose (unchanged from the review): `approval.py`, `approvals.py` and `grants.py`; the thin adapters over `run_operation`.

## 8. Not covered

Code-level security review of the stages (per PR), the design of the UI views over runs (#194), behaviour of several machines, and readers of `audit.jsonl` outside the repository.

## 9. Decisions recorded

None yet. To be filled in when Hùng answers section 6.
