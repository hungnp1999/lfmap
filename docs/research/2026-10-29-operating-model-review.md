# Operating Model v1: review against how the project runs today

- Date: 2026-10-29 · Author: Claude (Managing Agent) · Requested by: Hùng
- Status: **proposed**, waiting for Hùng to pick an option (§4).
- Input: the owner's proposal "LFMAP Operating Model v1" (GitHub Issues as the single source of task state, Agent View, two approval gates, a `pm.ps1` status script) and the "Planning Platform" concept v0.1 (kept outside this public repository).
- Baseline: governance of 2026-10-22 (the project's coordinator and threads act as Managing Agent and open Working Agent sessions themselves), grants of the same day (Claude merges when tests and CodeQL are green), provenance rules (`docs/DEVELOPMENT_PROVENANCE.md`), the Antigravity Deputy trial 2026-10-30 to 2026-11-20 (`docs/handoff/2026-10-29-antigravity-deputy.md`), ADR-001..021.
- Facts about Claude Code features that could not be checked from the cloud session are marked **[verify]**.

## 1. Verdict in one paragraph

The diagnosis is right: task state lives in chat history, so every "where are we, what next" costs quota and the owner's attention. The cure (GitHub Issues + a Projects board as the source of truth, mandatory file scope per task, a status view that costs no tokens) fits the project and its principles. Two parts do not fit how the project actually runs and should change before adoption: the **owner as dispatcher** (`pm next` → `claude --bg` → plan approval in Agent View for every task) undoes the 2026-10-22 delegation and only works at the DIEP-ANH terminal, which the owner often cannot reach; and **"owner approves every PR"** undoes the merge grant. The project's own data also shows that what decides whether a task succeeds is the **shape of the task card**, not the tracker, so the Issue template must carry the card rules learned this week.

## 2. Conflicts and overlaps

| # | Proposal item | Current rule or fact | Proposed resolution |
| --- | --- | --- | --- |
| C1 | Owner runs `pm next`, starts `claude --bg "Làm issue #N"`, approves each plan in Agent View (Gate 1) | Governance 2026-10-22: the Managing Agent prepares and opens Working Agent sessions itself; the owner is asked only for out-of-scope permissions or human-only actions. The owner is often at an office PC with a browser only; Agent View is a local terminal UI on DIEP-ANH **[verify version/plan requirements]** | Keep the dispatcher role with the Managing Agent. Gate 1 moves up one level: the owner approves the **handoff** ("chốt") once per feature, not each task's plan. Agent View is optional, for when the owner is at DIEP-ANH |
| C2 | Gate 2: owner reviews and merges every PR | Grant 3: Claude merges when every check is green; docs-only PRs merge without asking | Gate 2 only for PRs labelled `gate:po` (ADR change, security or licence policy, `.claude/`, release, anything irreversible). Everything else: Claude merges on green and reports in the daily report |
| C3 | `ROADMAP.md` keeps Phase plan and exit criteria in the repo (§9.3) | `CLAUDE.md`: no ROADMAP/DECISIONS files in this repo; the Roadmap is `05_Roadmap.md` in the project files | Milestone descriptions link to the Roadmap section; no new file |
| C4 | Milestones Phase 0..3 | Phase 0 and Phase 1 MVP are closed (accepted 2026-10-22); work now is Phase 1b leftovers and Phase 2a (EventBus), 2b per ADR-021 | Milestones `Phase 1b`, `Phase 2a`, `Phase 2b` only |
| C5 | Branches `cc/<N>-slug` | Cloud sessions are pinned by the harness to `claude/...` branches | Branch name free; the link is `Closes #N` in the PR body (already in the PR template's spirit). `ag/<N>-slug` for Antigravity is fine |
| C6 | Executors `exec:CC / exec:AG / exec:PO` | Three executors already exist: `[CC]`, `[AG]`, `[QW]` (qwen gets S cards with frozen tests first, ADR-004, B6) | Add `exec:QW` |
| C7 | `scripts/pm.ps1` via `gh` | Cloud sessions have no PowerShell and use the GitHub MCP tools, not `gh`; business logic belongs in a plugin `Tool` class; a GitHub token is a secret | Phase A: no script. The Projects board with saved views answers "status / next / review" at zero tokens. Phase B (only if the pain log shows the board is not enough): a small Python tool shaped as the future `lfmap-pm` plugin, reading GitHub through `gh api` on DIEP-ANH |
| C8 | `.claude/settings.json` deny `Bash(git push origin main:*)`, `rm -rf` | Pattern denies are easy to bypass (`git push origin HEAD:main`); user-level allow rules already exist on DIEP-ANH (2026-10-22) | Real guard = GitHub ruleset "require a PR on main" (already a pending owner item from the Deputy trial). Repo `settings.json` changes still go through `/security-review` |
| C9 | "Approval style is inconsistent (cards vs typed commands)" | Partly structural: the DIEP-ANH auto-mode classifier accepts only approvals typed by the owner in the Remote Control thread; `lfmap approvals approve` deliberately needs a human at a TTY | Cannot be unified by settings. Keep the rule "one list of asks in project chat"; for RC, one combined approval sentence per day with an expiry, as the daily report already does |
| C10 | New ADR-0XX | ADR-022 is still Proposed (PR #77); ADRs record architecture | Record this as a project-instruction change plus ADR-023 only if the owner wants it in the ADR log (draft in §6) |
| C11 | Two fixed approval windows (09:00 and 17:00) | Matches the owner's habit of handling approvals in one sitting | Adopt; the coordinator posts the batched list just before each window |

Overlaps with no conflict: file scope per task (already in `[AG]` cards), `needs-decision` (same as the coordinator's pending-decision list), model choice (Opus for planning, Sonnet for small reviews, already in the Deputy plan), pain log and quota log (new, cheap).

## 3. Evidence from this project

| Observation | Source | What it means for the operating model |
| --- | --- | --- |
| qwen 14b + store, numbered step-by-step cards TC-O1..O3: **9/9** first-round green; EventBus cards TC-E1..E3 written as goal + tests: **1/9**; the same naming module as one card (TC-N2): 0/6 in W0 | qwen batch 2026-10-29, `2026-10-28-working-model-bench.md` §11 | Task success depends on card shape per executor. The Issue template needs a "Steps" section required for `exec:QW` and `exec:AG` |
| W0: 14b first-round green 10 % without the experience store, 33 % with it | W0 bench, 90 runs | Lessons learned must be fed back into the next card; an Issue closed without a lesson loses data |
| Pro weekly quota ~30 % used in under 24 h (2026-10-28/29) with several parallel threads, RC runs and Opus everywhere | Deputy trial plan | The big costs are long Opus threads and parallel sessions, not status questions. Cap parallel threads at 3, Sonnet for routine reviews, log `/usage` weekly |
| GPU on DIEP-ANH is a serial resource (bench, re-judge, qwen batches queued by hand); Office tests must not overlap (PowerPoint PID race) | coordinator GPU queue | Tasks need a "resource" field (`res:gpu`, `res:office`), and "next" must respect it |
| The 22:00 daily report did not fire 24–27/10 and nobody noticed for four days | daily-report record | Scheduled jobs need a health check; a board view "last report" or a missed-run alert |
| Approvals with scope and expiry (24 h default, 48 h for W0) worked and left evidence | W0, D3b approvals | Keep grants as first-class records (who, where, scope, expiry) |

## 4. Options

**A. Adopt v1 as written.** Issues + board + Agent View + owner-driven two gates + `pm.ps1`.
Pros: complete, close to the document. Cons: C1, C2 and C7 conflict with current rules; the owner becomes the bottleneck again and needs DIEP-ANH for every task start; pwsh script cannot run in the cloud.

**B. Adapted v1 ("Managing Agent drives, GitHub records") — recommended.**
1. GitHub is the record: one Issue per task, one Projects board for all three repositories (Projects v2 is user-level), Milestones per open phase, labels `exec:CC/AG/QW/PO`, `P1..P3`, `res:gpu/office`, `blocked`, `needs-decision`, `gate:po`, `security-review`.
2. The Managing Agent turns each approved handoff into Issues, starts sessions, keeps the board current, merges green PRs within the grants. The owner's two gates: **handoff approval** (per feature) and **`gate:po` PRs** (risk class), both in the two daily windows.
3. Zero-token status = board views ("Next", "Waiting for me", "Blocked", "Running") + the daily report. No script for two weeks.
4. Card rules move into the Issue template (file scope, steps for QW/AG, frozen tests, resource, executor).
5. Pilot on lfmap only, from 2026-10-30, reviewed together with the Deputy trial on 2026-11-12 (two weeks) and 2026-11-20.
Pros: keeps the delegation, works from a browser or phone, no new code, reuses the Deputy trial window. Cons: depends on Claude keeping the board current (mitigation: board sync is part of each thread's "done" checklist); GitHub dependency (acceptable: already the code host).

**C. Minimal.** Keep chat-based tracking; only add file scope, the pain log and the quota log.
Pros: zero setup. Cons: V1, V3, V4 stay; status still costs tokens.

## 5. Changes needed under option B

| Where | Change | Who / env |
| --- | --- | --- |
| Project instructions | New section "Quản lý công việc" (draft text in the project files, `operating-model/2026-10-29-de-xuat.md`) | Owner pastes after approval |
| Handoff template (project instructions "File bàn giao") | Each task adds: Roadmap x.y, Executor, Priority, Blocked by, File scope (may / must not touch), Steps (required for QW/AG), Frozen tests, Resource, Gate | Same |
| `.github/ISSUE_TEMPLATE/task.md` in lfmap | New, same fields | `[AG]` pilot candidate, Claude reviews |
| PR template | Add `Closes #N` and an "Executor" line | `[CC]` small |
| Labels, Milestones | Create via `gh` on DIEP-ANH (RC) or the web UI | `[CC]` via RC, 10 min |
| Projects board | Create the user-level board and four saved views | Owner, 5 min on the web (no API in cloud tools) |
| GitHub ruleset | "Require a pull request before merging" on `main` of lfmap and MarkitdownTool | Owner (already pending) |
| Memory | One file `operating-model` (option chosen, labels, gates, pilot dates) | Claude |
| Skills | None now. After two weeks, if "handoff → Issues" repeats, propose a project skill for it | Claude |
| Logs | Pain log and weekly quota log in the private project files (not this public repo) | Claude + owner one line each |

## 6. ADR draft (only if the owner wants it in the ADR log)

```
### ADR-023: GitHub Issues record task state; the Managing Agent dispatches; approvals by risk class
- Status: Proposed
- Date: 2026-10-29
- Context: task state lived in chat; the owner had to ask the AI for status and next steps,
  approvals were scattered, quota was spent on coordination.
- Decision: every task is a GitHub Issue on one Projects board (milestone = open phase;
  labels exec/priority/resource/gate). The Managing Agent turns approved handoffs into
  Issues, starts Working Agent sessions and keeps the board current. The owner approves
  handoffs and PRs labelled gate:po, in two daily windows; other PRs merge on green under
  the 2026-10-22 grants. Status is read from board views, not from Claude.
- Alternatives: BACKLOG.md (no board, manual sync); third-party plugins and SaaS
  connectors (policy of 2026-10-28, data leaves the machine); owner-dispatched sessions
  with per-task plan approval (re-centralises work on the owner; needs the DIEP-ANH terminal).
- Consequences: + one source of truth, zero-token status, works from a browser;
  - dependency on GitHub for task tracking, discipline needed to keep Issues current.
```

## 7. Open questions for the owner

1. Option A, B or C (recommended B)?
2. Approval windows: 09:00 and 17:00 Vietnam time, or other times?
3. Record as ADR-023, or as a project-instruction change only?
