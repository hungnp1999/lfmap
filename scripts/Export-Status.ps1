<#
.SYNOPSIS
Export read-only status snapshots (project board and Dependabot alerts) for Cloud sessions.

.DESCRIPTION
Cloud sessions cannot read the user-owned Projects board (the proxy blocks GraphQL) and get 403 on Dependabot
alerts. This script runs on pc-01 under the signed-in `gh` (no token is created or stored) and writes
  status/board.json       items of project 2: number, title, status, start, due, labels
  status/dependabot.json  open alerts of lfmap, MarkitdownTool, isomp: package, severity, advisory, manifest
into a dedicated clone of the data branch `status-snapshot` (never `main`, which requires a PR). It commits and
pushes only when the content changed. Only metadata of the three repositories is kept; issue bodies are dropped.
Log: %LOCALAPPDATA%\lfmap\logs\status-export.log. Exit code 0 on success (changed or not), 1 on failure.

.EXAMPLE
pwsh -NoProfile -File scripts\Export-Status.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$Owner = 'hungnp1999',
    [int]$Project = 2,
    [string[]]$Repos = @('lfmap', 'MarkitdownTool', 'isomp'),
    [string]$Branch = 'status-snapshot',
    [string]$CloneDir = (Join-Path $env:LOCALAPPDATA 'lfmap\status-repo'),
    [string]$DevEnvironment = 'pc-01',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$logDir = Join-Path $env:LOCALAPPDATA 'lfmap\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir 'status-export.log'
function Log([string]$Text) { Add-Content -Path $log -Encoding utf8 -Value "$(Get-Date -Format 's') $Text" }

function Invoke-Git {
    $output = & git -C $CloneDir @args 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') failed: $($output -join ' ')" }
    return $output
}

function Get-Json([string[]]$GhArgs) {
    $text = & gh @GhArgs 2>&1
    if ($LASTEXITCODE -ne 0) { throw "gh $($GhArgs -join ' ') failed: $($text -join ' ')" }
    return ($text -join "`n") | ConvertFrom-Json -Depth 20
}

function Get-Board {
    $data = Get-Json @('project', 'item-list', "$Project", '--owner', $Owner, '--format', 'json', '--limit', '1000')
    $items = foreach ($item in $data.items) {
        $content = $item.content
        [ordered]@{
            number = $content.number
            repo   = $content.repository
            title  = $item.title
            type   = $content.type
            status = $item.status
            start  = $item.'start date'
            due    = $item.'due date'
            labels = @($item.labels)
        }
    }
    return [ordered]@{ project = $Project; owner = $Owner; items = @($items | Sort-Object { $_.repo }, { [int]$_.number }) }
}

function Get-Alerts {
    $state = [ordered]@{}
    $alerts = foreach ($repo in $Repos) {
        try {
            $rows = Get-Json @('api', '--paginate', "repos/$Owner/$repo/dependabot/alerts?state=open&per_page=100")
            $state[$repo] = 'ok'
        } catch {
            $state[$repo] = if ("$_" -match 'disabled') { 'disabled' } else { throw }
            continue
        }
        foreach ($row in @($rows)) {
            [ordered]@{
                repo     = $repo
                number   = $row.number
                package  = $row.dependency.package.name
                severity = $row.security_advisory.severity
                advisory = $row.security_advisory.ghsa_id
                cve      = $row.security_advisory.cve_id
                manifest = $row.dependency.manifest_path
                created  = $row.created_at
            }
        }
    }
    return [ordered]@{ owner = $Owner; repos = $state; alerts = @($alerts | Sort-Object { $_.repo }, { [int]$_.number }) }
}

function Save-Json($Value, [string]$Path) {
    $text = ($Value | ConvertTo-Json -Depth 10) + "`n"
    [System.IO.File]::WriteAllText($Path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

try {
    $board = Get-Board
    $alerts = Get-Alerts
    if ($DryRun) {
        Write-Output "board items: $($board.items.Count); open alerts: $($alerts.alerts.Count)"
        exit 0
    }
    $url = "https://github.com/$Owner/lfmap.git"
    if (-not (Test-Path -LiteralPath (Join-Path $CloneDir '.git'))) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $CloneDir) | Out-Null
        $cloned = $false
        & git clone --quiet --branch $Branch --single-branch $url $CloneDir 2>$null
        if ($LASTEXITCODE -eq 0) { $cloned = $true }
        if (-not $cloned) {
            & git clone --quiet --no-checkout --depth 1 $url $CloneDir
            if ($LASTEXITCODE -ne 0) { throw 'git clone failed' }
            Invoke-Git checkout --quiet --orphan $Branch | Out-Null
            Invoke-Git rm -rf --quiet --ignore-unmatch . | Out-Null
        }
    } else {
        & git -C $CloneDir fetch --quiet origin $Branch 2>$null
        if ($LASTEXITCODE -eq 0) { Invoke-Git reset --quiet --hard "origin/$Branch" | Out-Null }
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $CloneDir 'status') | Out-Null
    Save-Json $board (Join-Path $CloneDir 'status\board.json')
    Save-Json $alerts (Join-Path $CloneDir 'status\dependabot.json')
    Invoke-Git add status | Out-Null
    $staged = & git -C $CloneDir diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { Log "OK unchanged ($($board.items.Count) items, $($alerts.alerts.Count) alerts)"; exit 0 }
    $message = "status: snapshot $(Get-Date -Format 'yyyy-MM-dd HH:mm')`n`nDev-Environment: $DevEnvironment"
    Invoke-Git commit --quiet -m $message | Out-Null
    Invoke-Git push --quiet -u origin $Branch | Out-Null
    Log "OK pushed ($($board.items.Count) items, $($alerts.alerts.Count) alerts)"
    exit 0
} catch {
    Log "FAIL $($_.Exception.Message)"
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
