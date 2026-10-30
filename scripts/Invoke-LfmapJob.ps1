<#
.SYNOPSIS
Run one LFMAP job (`lfmap jobs run <id>`) and append one JSON line to the daily job log.

.DESCRIPTION
Task Scheduler calls this script for every task in \LFMAP\ (see docs/jobs.md).
`lfmap jobs register` starts it from the runtime root (`[runtime] root` in jobs.toml, ADR-023) and passes that
root as -RepoPath. The script refuses a -RepoPath other than its own repository, so the runner and the code it
runs always come from the same reviewed tree.
Log: %LOCALAPPDATA%\lfmap\logs\jobs-YYYY-MM-DD.jsonl. The exit code is the one of `lfmap`
(0 success, 1 ToolError, 2 other error); 2 also when uv cannot be found or -RepoPath is another tree.

.EXAMPLE
pwsh -NoProfile -File scripts\Invoke-LfmapJob.ps1 -JobId echo-hello
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z][a-z0-9-]*$')]
    [string]$JobId,

    [string]$RepoPath = (Split-Path -Parent $PSScriptRoot),

    [string]$UvPath
)

$ErrorActionPreference = 'Stop'
$MaxText = 4000

function Limit-Text([string]$Text) {
    if ($Text.Length -gt $MaxText) { return $Text.Substring(0, $MaxText) }
    return $Text
}

function Find-Uv {
    $command = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    $winget = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe'
    if (Test-Path -LiteralPath $winget -PathType Leaf) { return $winget }
    return $null
}

if (-not $UvPath) { $UvPath = Find-Uv }
if (-not $UvPath -or -not (Test-Path -LiteralPath $UvPath -PathType Leaf)) {
    [Console]::Error.WriteLine("uv was not found; pass -UvPath")
    exit 2
}
$UvPath = (Resolve-Path -LiteralPath $UvPath).Path

$ownRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$RepoPath = [System.IO.Path]::GetFullPath($RepoPath).TrimEnd('\')
if ($RepoPath -ine $ownRoot) {
    [Console]::Error.WriteLine("-RepoPath $RepoPath is not the repository of this script ($ownRoot)")
    exit 2
}

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$started = Get-Date
$stderrFile = New-TemporaryFile
try {
    # Text on stderr from a native command must not stop the script; the exit code decides.
    $ErrorActionPreference = 'Continue'
    $stdout =(& $UvPath run --directory $RepoPath lfmap jobs run $JobId --json 2> $stderrFile.FullName) -join "`n"
    $exitCode = $LASTEXITCODE
    $stderr = (Get-Content -LiteralPath $stderrFile.FullName -Raw -Encoding utf8) ?? ''
}
finally {
    $ErrorActionPreference = 'Stop'
    Remove-Item -LiteralPath $stderrFile.FullName -ErrorAction SilentlyContinue
}
$finished = Get-Date

$logDir = Join-Path $env:LOCALAPPDATA 'lfmap\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("jobs-{0}.jsonl" -f $started.ToString('yyyy-MM-dd'))
$record = [ordered]@{
    started   = $started.ToString('o')
    finished  = $finished.ToString('o')
    job       = $JobId
    exit_code = $exitCode
    stdout    = Limit-Text $stdout
    stderr    = Limit-Text $stderr.TrimEnd()
}
$line = ($record | ConvertTo-Json -Compress) + "`n"
[System.IO.File]::AppendAllText($logFile, $line, [System.Text.UTF8Encoding]::new($false))

if ($stdout) { Write-Output $stdout }
if ($stderr) { [Console]::Error.Write($stderr) }
exit $exitCode
