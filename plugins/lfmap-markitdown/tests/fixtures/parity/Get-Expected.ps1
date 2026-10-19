<#
.SYNOPSIS
    TC-M8: record how the installed MarkitdownTool classifies the parity fixtures.

.DESCRIPTION
    Runs `markitdowntool.exe classify --json` on this folder and writes expected.json next to
    this script. Reads only this folder (MARKITDOWNTOOL_ALLOWED_ROOTS is set to it for the run);
    nothing is converted, written elsewhere or sent anywhere.

.EXAMPLE
    pwsh -NoProfile -File .\plugins\lfmap-markitdown\tests\fixtures\parity\Get-Expected.ps1
#>
param(
    [string]$Exe = (Join-Path $env:LOCALAPPDATA 'Programs\MarkitdownTool\markitdowntool.exe')
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Exe)) { throw "markitdowntool.exe not found at $Exe; pass -Exe <path>." }

$folder = $PSScriptRoot
$previous = $env:MARKITDOWNTOOL_ALLOWED_ROOTS
$env:MARKITDOWNTOOL_ALLOWED_ROOTS = $folder
try {
    $version = (& $Exe info --json | ConvertFrom-Json).version
    $raw = & $Exe classify $folder --json
    if ($LASTEXITCODE -ne 0) { throw "classify failed with exit code $LASTEXITCODE" }
} finally {
    $env:MARKITDOWNTOOL_ALLOWED_ROOTS = $previous
}

$result = $raw | ConvertFrom-Json
$files = foreach ($file in $result.files) {
    [ordered]@{
        name              = Split-Path $file.path -Leaf
        supported         = $file.supported
        needs_ocr         = $file.needs_ocr
        markdown_eligible = $file.markdown_eligible
        reason_code       = $file.reason_code
        text_quality      = $file.text_quality
        low_quality_pages = @($file.low_quality_pages)
    }
}
$expected = [ordered]@{ markitdowntool_version = $version; files = @($files) }
$target = Join-Path $folder 'expected.json'
$expected | ConvertTo-Json -Depth 5 | Set-Content -Path $target -Encoding utf8NoBOM
Write-Host "Wrote $target ($(@($files).Count) files, MarkitdownTool $version)"
Get-Content $target
