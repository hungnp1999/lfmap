# Docling spike (Roadmap 1.2) on DIEP-ANH. Run from PowerShell 7; everything stays in D:\Development\lfmap-tools\docling-spike.
# Network: PyPI (packages), huggingface.co (layout + TableFormer weights, one time) and, with -Gpu, download.pytorch.org.
# Conversions run with HF_HUB_OFFLINE=1, so any further download attempt fails instead of happening silently.
param(
    [string]$Root = "D:\Development\lfmap-tools\docling-spike",
    [string]$Spike = $PSScriptRoot,
    [switch]$Gpu  # also install CUDA torch (cu128, needed for RTX 50xx) and repeat the run on the GPU with nvidia-smi logging
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Root | Out-Null
Set-Location $Root
$env:ORT_DISABLE_TELEMETRY = "1"
$py = Join-Path $Root ".venv\Scripts\python.exe"
$models = Join-Path $Root "models"
$pdfs = Join-Path $Root "pdfs"

function Get-FolderMB([string]$Path) { "{0:N0} MB" -f ((Get-ChildItem $Path -Recurse -File | Measure-Object Length -Sum).Sum / 1MB) }

function Invoke-Compare([string]$Device, [string]$Out) {
    $env:HF_HUB_OFFLINE = "1"
    $env:ACCEL_DEVICE = $Device
    & $py -I (Join-Path $Spike "compare.py") $pdfs (Join-Path $Root $Out) $models 2>&1 | Tee-Object (Join-Path $Root "$Out.log")
    Remove-Item Env:HF_HUB_OFFLINE
}

uv venv --python 3.12 .venv
uv pip install --python $py "docling-slim[format-pdf,models-local,convert-core,cli]==2.142.0" "markitdown[pdf]==0.1.8" reportlab
"--- CPU install: $(Get-FolderMB .venv), $((uv pip list --python $py | Measure-Object -Line).Lines - 2) packages"

& $py -I (Join-Path $Spike "make_pdfs.py") $pdfs

"--- model download (huggingface.co)"
& (Join-Path $Root ".venv\Scripts\docling-tools.exe") models download layout tableformer -o $models
"--- models: $(Get-FolderMB $models)"
Get-ChildItem $models -Recurse -Filter README.md | ForEach-Object { "$($_.FullName): $((Select-String -Path $_.FullName -Pattern '^license:' | Select-Object -First 1).Line)" }

$tesseract = "C:\Program Files\Tesseract-OCR\tesseract.exe"
if (Test-Path $tesseract) { $env:TESSERACT_CMD = $tesseract; $env:OCR_LANG = "eng" }

"--- CPU run"
Invoke-Compare "cpu" "out-cpu"

if ($Gpu) {
    "--- GPU install (download.pytorch.org cu128)"
    uv pip install --python $py torch torchvision --index-url https://download.pytorch.org/whl/cu128 --reinstall
    & $py -I -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
    "--- GPU install: $(Get-FolderMB .venv)"
    $smiLog = Join-Path $Root "gpu-smi.csv"
    $smi = Start-Process nvidia-smi -ArgumentList "--query-gpu=timestamp,utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu", "--format=csv", "-lms", "500", "-f", $smiLog -PassThru -WindowStyle Hidden
    try {
        "--- GPU run"
        Invoke-Compare "cuda" "out-gpu"
    } finally {
        Stop-Process -Id $smi.Id -ErrorAction SilentlyContinue
    }
    $rows = Import-Csv $smiLog
    $util = $rows | ForEach-Object { [double]($_." utilization.gpu [%]" -replace '[^\d.]', '') }
    $mem = $rows | ForEach-Object { [double]($_." memory.used [MiB]" -replace '[^\d.]', '') }
    "--- GPU samples: $($rows.Count), util max $(($util | Measure-Object -Maximum).Maximum)% avg {0:N0}%, VRAM max $(($mem | Measure-Object -Maximum).Maximum) MiB of $($rows[0].' memory.total [MiB]')" -f ($util | Measure-Object -Average).Average
}
"--- done; send back out-cpu.log, out-gpu.log, gpu-smi.csv and the out-* folders"
