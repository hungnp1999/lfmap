# Operating Model B: pilot review (#260)

- Date: 2026-11-13 · Author: Claude (Managing Agent, review role) · Decision: Hùng, Sunday 15/11 about 19:30 VN
- Scope: pilot 29/10 to 13/11 of the model chosen in `docs/research/2026-10-29-operating-model-review.md` (option B), plus the five commitments of 04/11.
- Model B in one line: Issues and the board "LFMAP work" are the task record, the Managing Agent dispatches, Hùng has two gates (handoff, `gate:po` PRs) handled at 09:00 and 17:00 VN, Cloud reads a `status-snapshot` export because it cannot reach Projects GraphQL (`docs/status-snapshot.md`).

## 1. What the numbers say

From GitHub (lfmap, 30/10 to 13/11) and the 13/11 22:56 snapshot of the board:

| Measure | Value |
| --- | --- |
| Issues created / closed | 110 / 64 |
| PRs merged / closed unmerged | 108 / 1 |
| Merged PRs labelled `gate:po` | 6 (about 5 %): the second gate is rarely hit |
| Board items Done / Ready / Backlog | 155 / 11 / 17 |
| Open items past their due date | 3 of 28 open (#191, #197, #260) |

Not measurable from the repo: how many slips were caused by quota (the `/usage` log is Hùng's, in the private project files). This review does not claim a number for it.

## 2. What worked

- **One issue per thread, `Closes #N` in the PR.** Any thread or session can find its task; "where are we" is answered by a link.
- **Two windows** collapsed the approvals into one list; `gate:po` kept ADR, security and release changes in front of Hùng without making him review the other ~100 PRs.
- **Daily budget and Sonnet by default** (04/11 commitments 1 and 2) ended the early-week quota crash of 29/10 to 01/11.
- **Status snapshot** gives Cloud sessions read access to the board at zero tokens.
- **Task card shape** (steps, frozen tests, file scope) is now part of the template.

## 3. What did not work

| Problem | Evidence | Cost | Already fixed? |
| --- | --- | --- | --- |
| Threads wrote implementation code | #189, #196 (10/11) | Role rule broken; Hùng kept the code | Rule restated 10/11; relies on discipline, not a check |
| PRs without CI | 09/11: GitHub runs no CI while a PR conflicts with `main`, caused by edits to `CHANGELOG.md` | Delays, extra rebases | Yes: changelog fragments (`changelog.d/`) |
| A `DONE` went unseen for 6 minutes (13/11, #271) | No PR existed to subscribe to | Hùng had to relay | Yes: draft PR at first commit + `DONE` comment ([cc-session-protocol] in project memory) |
| Board lags reality | Snapshot runs 08:30 and 16:30 on pc-01 only; merged PRs such as #265 and #272 still show Backlog at 22:56; items past due stay "Ready" | The board is wrong exactly when Cloud reads it | No |
| Board needs pc-01 | Cloud cannot move cards; edits wait for DIEP-ANH or Hùng's browser | Status upkeep is a recurring chore for a solo owner | No |
| Windows are fixed, work is not | Several 09:00/17:00 lists were empty or contained one item | Overhead with no content | No |

Root cause of the two open items: the board is a **second copy** of state that already exists on the issue (open/closed, labels, linked PR). Every copy that a human or a Windows task must refresh will drift.

## 4. Options

### A. Keep B as is

Nothing changes.

- Consequences: no migration; known drift stays; each new thread rule still depends on discipline. Overhead is unchanged (snapshot task, board upkeep, two windows).
- Fits solo maintenance: so-so. It works, but the weakest part (the board copy) keeps costing attention.

### B. Keep B, make the issue the only truth and the board a read-only view (recommended)

1. Issue state and labels are the truth. The board is a view; turn on the built-in Projects workflows (item closed → Done, PR merged → Done, new issue → Backlog; web setting, 2 minutes, Hùng) so no one moves cards by hand.
2. Questions about progress are answered from `gh`/GitHub issue lists first; the snapshot stays for the board view and Dependabot data but is no longer required to be fresh. Run it once daily at 08:30 instead of twice if the task ever fails.
3. Gates stay (`gate:po`, handoff approval), but the coordinator posts a window list only when it has at least one item; no empty 09:00/17:00 post.
4. Mechanical checks replace discipline where cheap: the PR template carries `Closes #N` and "Executor"; a thread that finds code in its own diff stops and hands a card to a Working Agent (already the rule; add it to the thread start prompt, not a new CI job).
5. Keep the five commitments of 04/11, and the draft-PR-plus-`DONE` protocol.

- Consequences: about 1 hour of change (workflow toggles, one paragraph in the instructions); removes the main drift without losing the board view Hùng likes; no new component.
- Fits solo maintenance: best of the three.

### C. Drop the board and the snapshot; issues and labels only

Delete the Projects board and `status-export` tasks; use issue lists filtered by label and milestone.

- Consequences: lowest overhead and one fewer scheduled task on pc-01 (and one fewer thing for ADR-023 to cover). But Hùng loses the Gantt-like view and Kanban he uses in the 09:00/17:00 sessions, the daily report must rebuild its tables from issue queries, and re-creating the board later is manual.
- Fits solo maintenance: good for upkeep, weak for reading at a glance. Worth it only if the board is seldom opened.

Dropping everything (back to chat-only tracking) is not offered: it re-creates the problem the pilot solved (state in chat, status costs tokens).

## 5. Recommendation

**Option B.** The evidence says the record (issues, one per thread, linked PRs) worked and the gates are cheap; the failures are in the copy of state (board) and in rules that rely on memory. Fix the first by automation, the second with the changelog-fragment and `DONE` mechanisms already shipped. Choose C instead only if Hùng says he rarely looks at the board.

## 6. If Hùng chooses

| Choice | Instruction changes for Hùng to paste | Other work |
| --- | --- | --- |
| A | None | Close #260 |
| B | Under "Nguồn sự thật": board is a view, issue state is truth; under "Hai cổng": post a window list only when it is not empty | Hùng enables the board workflows; Claude updates memory and the daily-report note |
| C | Remove the board link and the snapshot sentence; progress questions answered from issue queries | Claude removes `scripts/Export-Status.ps1` references via a PR; Hùng unregisters `\LFMAP-Runtime\status-export*` and closes the board |

Open questions: none that block the decision. The quota-caused slip count needs Hùng's `/usage` log if he wants it in the record.
