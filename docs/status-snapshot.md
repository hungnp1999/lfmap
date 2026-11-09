# Status snapshot for Cloud sessions

Cloud sessions cannot read the user-owned Projects board (the proxy blocks GraphQL) and get 403 on Dependabot alerts. `scripts/Export-Status.ps1` runs on pc-01 with the already signed-in `gh` and writes two read-only files:

| File | Content |
| --- | --- |
| `status/board.json` | Items of project 2: repo, number, title, type, status, start, due, labels. Issue bodies are dropped. |
| `status/dependabot.json` | Open Dependabot alerts of `lfmap`, `MarkitdownTool`, `isomp`: package, severity, advisory id, CVE, manifest, created. A repo with alerts disabled is marked `disabled` under `repos`. |

## Where it lands

`main` requires a PR, so the files live on the data branch **`status-snapshot`** (no shared history with `main`), kept in a separate clone at `%LOCALAPPDATA%\lfmap\status-repo`. The script commits and pushes only when the content changed; commits carry `Dev-Environment: pc-01` and are signed with the device key. A Cloud session reads them with `git fetch origin status-snapshot` and `git show origin/status-snapshot:status/board.json`.

## Schedule

`scripts/Register-StatusTask.ps1` (run once by the owner) creates `\LFMAP-Runtime\status-export` (08:30 and 16:30, before the 09:00 and 17:00 gates) and `\LFMAP-Runtime\status-export-at-logon`, both hidden through `run-hidden.vbs` like the `update` task. The tasks run as the owner while logged on; no password or token is stored and none is created. Log: `%LOCALAPPDATA%\lfmap\logs\status-export.log`.

## Data that leaves the machine

Only metadata of the three repositories (titles and labels of issues the owner already keeps on GitHub, alert metadata) goes back to GitHub. `pwsh scripts\Export-Status.ps1 -DryRun` fetches and counts without writing or pushing.

## Mistakes found while building it (2026-11-08)

- **First dry run failed:** isomp has Dependabot alerts disabled, so the API answers 403 and the whole export stopped. Fixed: that repo is marked `disabled` in `repos` and the export goes on.
- **First real run logged `FAIL` on its second pass:** the clone was made from the default branch, so `origin/status-snapshot` did not exist and `git reset` failed. The first pass had pushed correctly. Fixed with an explicit fetch refspec; two later runs reported `unchanged`.
- **Task path:** the tasks were first registered with `-ScriptPath` pointing at a Claude worktree, because the PR was not merged yet. After merge, re-run `Register-StatusTask.ps1 -ScriptPath D:\lfmap-runtime\scripts\Export-Status.ps1` so they do not depend on a worktree that may be deleted.
- **Auto-mode blocks:** pushing the data branch and opening the PR were refused until the owner approved them in the thread; no check was bypassed.
