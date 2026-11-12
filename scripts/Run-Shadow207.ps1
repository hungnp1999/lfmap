# Leading shadow round on the real Flows cases (lfmap #207). Run signed in as lfmap-agent (ADR-023), Ollama tray app running:
#   pwsh -NoProfile -File D:\Development\lfmap-shadow207\scripts\Run-Shadow207.ps1 -DryRun    # fake runner, no Ollama, no git changes
#   pwsh -NoProfile -File D:\Development\lfmap-shadow207\scripts\Run-Shadow207.ps1 -Preflight  # checks only
#   pwsh -NoProfile -File D:\Development\lfmap-shadow207\scripts\Run-Shadow207.ps1             # the round (rerunnable: finished cases are skipped)
# Runs in its own worktree of the agent clone (create it once, see PR #222); the agent clone itself is never touched.
# Changes no Ollama setting. Writes only results\<date>-shadow207 and the branch ag/shadow-207-results.
param([switch]$DryRun, [switch]$Preflight, [string]$Source = 'main', [string]$Repo = 'D:\Development\lfmap-shadow207')
$ErrorActionPreference = 'Stop'
if ($env:USERNAME -ne 'lfmap-agent' -and -not $DryRun) { throw "Run this as lfmap-agent (current user: $env:USERNAME)." }
$repo = $Repo; $branch = 'ag/shadow-207-results'; $spike = Join-Path $repo 'spikes\2a1-framework'
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $env:GH_TOKEN) { $env:GH_TOKEN = [Environment]::GetEnvironmentVariable('GH_TOKEN', 'User') }
if (-not $env:DEV_ENVIRONMENT) { $env:DEV_ENVIRONMENT = 'pc-01' }
function Invoke-Git { git.exe @args; if ($LASTEXITCODE) { throw "git $args failed ($LASTEXITCODE)" } }

# 1. Code: refuse a dirty clone, fast-forward to $Source (main, or the PR branch before it is merged).
if (git.exe -C $repo status --porcelain --untracked-files=no) { throw "$repo has uncommitted changes; stop." }
Invoke-Git -C $repo fetch origin
Invoke-Git -C $repo checkout $Source
Invoke-Git -C $repo pull --ff-only origin $Source
Set-Location $spike
uv sync --all-groups; if ($LASTEXITCODE) { throw 'uv sync failed' }

if ($DryRun) { uv run python shadow_round.py run --dry-run; exit $LASTEXITCODE }
# Gate worktrees lfmap-s207-* are created here, as this user, from the agent clone (idempotent; first run takes a few minutes).
uv run python shadow_round.py prepare; if ($LASTEXITCODE) { throw 'prepare failed' }
if ($Preflight) { uv run python shadow_round.py preflight; exit $LASTEXITCODE }

# 2. The round (preflight runs again inside; a failure exits before any model call).
uv run python shadow_round.py run
$rc = $LASTEXITCODE
$latest = Get-ChildItem (Join-Path $spike 'results') -Directory -Filter '*-shadow207' | Sort-Object Name | Select-Object -Last 1  # the round may cross midnight
if (-not $latest) { exit $rc }
$res = "spikes/2a1-framework/results/$($latest.Name)"

# 3. Commit only the results folder; push with the GH_TOKEN of this account.
Invoke-Git -C $repo checkout -B $branch
Invoke-Git -C $repo add -- $res
git.exe -C $repo diff --cached --quiet; $changed = $LASTEXITCODE
if ($changed) {
    Invoke-Git -C $repo commit -m 'spike: Leading shadow round on the real Flows cases results' -m 'Refs #207' --trailer 'Dev-Environment: pc-01' --trailer 'AI-Agent: lfmap-agent/spike-run'
    Invoke-Git -C $repo push -u origin $branch
}
Write-Host "`n===== SHADOW 207 SUMMARY (paste back) ====="
Get-Content (Join-Path $repo "$res\score.txt") -TotalCount 25 -ErrorAction SilentlyContinue
Write-Host "branch: $branch, commit made: $([bool]$changed). Next: open the PR for $branch (Refs #207)."
exit $rc
