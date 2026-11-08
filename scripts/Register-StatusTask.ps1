<#
.SYNOPSIS
Register the hidden scheduled tasks that run scripts\Export-Status.ps1 (twice a day and at logon).

.DESCRIPTION
Creates \LFMAP-Runtime\status-export (08:30 and 16:30) and \LFMAP-Runtime\status-export-at-logon (1 minute after
logon) for the current user, wrapped in the same run-hidden.vbs as the `update` task so no window appears.
No password or token is stored: the tasks run only while the user is logged on, with the signed-in `gh`.
Run once in a PowerShell 7 window as the owner; re-running replaces the tasks.

.EXAMPLE
pwsh -NoProfile -File scripts\Register-StatusTask.ps1 -ScriptPath D:\lfmap-runtime\scripts\Export-Status.ps1
#>
[CmdletBinding()]
param(
    [string]$ScriptPath = (Join-Path $PSScriptRoot 'Export-Status.ps1'),
    [string]$Bin = (Join-Path $env:LOCALAPPDATA 'lfmap\bin'),
    [string]$Pwsh = (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\pwsh.exe')
)

$ErrorActionPreference = 'Stop'
foreach ($path in $ScriptPath, (Join-Path $Bin 'run-hidden.vbs'), $Pwsh) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "not found: $path" }
}
$arguments = '//B //Nologo "{0}\run-hidden.vbs" "{1}" "-NoProfile" "-ExecutionPolicy" "Bypass" "-File" "{2}"' -f $Bin, $Pwsh, $ScriptPath
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\wscript.exe" -Argument $arguments
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$logon.Delay = 'PT1M'
$tasks = @{
    'status-export'          = @((New-ScheduledTaskTrigger -Daily -At '08:30'), (New-ScheduledTaskTrigger -Daily -At '16:30'))
    'status-export-at-logon' = @($logon)
}
foreach ($name in $tasks.Keys) {
    Register-ScheduledTask -TaskPath '\LFMAP-Runtime\' -TaskName $name -Action $action -Trigger $tasks[$name] `
        -Principal $principal -Settings $settings -Force | Out-Null
    "registered \LFMAP-Runtime\$name"
}
