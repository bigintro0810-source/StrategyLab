# Strategy Lab - distribution package build script
#
# Builds a self-contained, double-click-to-run distribution in dist\StrategyLab\.
#
# Uses "embeddable Python + pip install + batch launcher" instead of PyInstaller.
# Reason: gui_app.py launches main.py via subprocess.run([sys.executable, "main.py", ...])
# (main.py's ProcessPoolExecutor uses Windows' "spawn" start method - running it
# in-process from Streamlit risks worker processes re-launching the Streamlit app
# itself, a known footgun). If frozen with PyInstaller, sys.executable would point
# back at the frozen GUI exe itself, breaking that subprocess call. With an embedded
# Python, sys.executable correctly points at the bundled real python.exe, so the
# existing code works unmodified.
#
# Run from the repo root: & ".\build_package.ps1"
# (No -ExecutionPolicy Bypass needed if the current session's Process-scope policy
# already allows script execution.)

$ErrorActionPreference = "Stop"

$PythonVersion = "3.13.14"
$PythonEmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"

$RepoRoot = $PSScriptRoot
$DistRoot = Join-Path $RepoRoot "dist"
$AppDir = Join-Path $DistRoot "StrategyLab"
$PythonDir = Join-Path $AppDir "python"
$AppSrcDir = Join-Path $AppDir "app"

Write-Host "=== Strategy Lab package build ===" -ForegroundColor Cyan

if (Test-Path $DistRoot) {
    Write-Host "Removing existing dist folder: $DistRoot"
    Remove-Item -Recurse -Force $DistRoot
}

New-Item -ItemType Directory -Force -Path $PythonDir | Out-Null
New-Item -ItemType Directory -Force -Path $AppSrcDir | Out-Null

# --- 1. Download and extract the Python embeddable package ---
$ZipPath = Join-Path $env:TEMP "strategylab-python-embed.zip"
Write-Host "[1/8] Downloading Python $PythonVersion (embeddable)..."
Invoke-WebRequest -Uri $PythonEmbedUrl -OutFile $ZipPath
Expand-Archive -Path $ZipPath -DestinationPath $PythonDir -Force
Remove-Item $ZipPath

# --- 2. Enable site-packages and the app directory (edit the ._pth file) ---
# A ._pth file, if present, replaces Python's normal sys.path initialization
# entirely - it does NOT automatically add the invoked script's own directory
# the way a non-restricted "python main.py" run would. Without the explicit
# "..\app" entry here, `from engine.xxx import yyy` inside main.py/gui_app.py
# fails with ModuleNotFoundError even though main.py itself is found and runs.
Write-Host "[2/8] Enabling site-packages..."
$PthFile = Get-ChildItem -Path $PythonDir -Filter "python*._pth" | Select-Object -First 1
if (-not $PthFile) {
    throw "._pth file not found - check the PythonVersion value."
}
(Get-Content $PthFile.FullName) -replace '^#\s*import site', 'import site' | Set-Content $PthFile.FullName
Add-Content -Path $PthFile.FullName -Value "..\app"
Write-Host "  -> updated $($PthFile.Name)"

# --- 3. Bootstrap pip ---
Write-Host "[3/8] Installing pip..."
$GetPipPath = Join-Path $env:TEMP "strategylab-get-pip.py"
Invoke-WebRequest -Uri $GetPipUrl -OutFile $GetPipPath
& "$PythonDir\python.exe" $GetPipPath --no-warn-script-location
Remove-Item $GetPipPath

# --- 4. Install dependencies ---
Write-Host "[4/8] Installing dependencies (pandas/numpy/streamlit/fpdf2/optuna)..."
Write-Host "  (this can take a few minutes)"
& "$PythonDir\python.exe" -m pip install --no-warn-script-location -r "$RepoRoot\requirements.txt"

# --- 5. Copy the application source ---
Write-Host "[5/8] Copying application files..."

$FilesToCopy = @(
    "main.py", "gui_app.py", "walk_forward.py", "analyze_walk_forward.py",
    "analyze_monthly.py", "analyze_yearly.py", "analyze_stability.py",
    "analyze_sensitivity.py", "analyze_confidence.py", "compare_signals.py",
    "compare_tradingview.py", "equity_curve.py", "monte_carlo.py",
    "rerank_results.py", "strategy_manager.py", "requirements.txt",
    "generate_pinescript.py", "import_broker_csv.py"
)

foreach ($file in $FilesToCopy) {
    $srcPath = Join-Path $RepoRoot $file
    if (Test-Path $srcPath) {
        Copy-Item $srcPath -Destination $AppSrcDir
    }
}

Copy-Item (Join-Path $RepoRoot "engine") -Destination $AppSrcDir -Recurse
Copy-Item (Join-Path $RepoRoot "strategy_configs") -Destination $AppSrcDir -Recurse
Copy-Item (Join-Path $RepoRoot "config") -Destination $AppSrcDir -Recurse -Exclude "__pycache__"

# --- 6. Create an empty data/raw folder with instructions ---
Write-Host "[6/8] Preparing data folder..."
$DataRawDir = Join-Path $AppSrcDir "data\raw"
New-Item -ItemType Directory -Force -Path $DataRawDir | Out-Null
Copy-Item (Join-Path $RepoRoot "packaging\data_raw_README.txt") -Destination (Join-Path $DataRawDir "README.txt")

# --- 7. Create run.bat ---
Write-Host "[7/8] Creating launcher..."
$RunBatContent = @'
@echo off
cd /d "%~dp0app"
"%~dp0python\python.exe" -m streamlit run gui_app.py
pause
'@
Set-Content -Path (Join-Path $AppDir "run.bat") -Value $RunBatContent -Encoding Default

# --- 8. Place end-user README / disclaimer ---
Write-Host "[8/8] Placing README..."
Copy-Item (Join-Path $RepoRoot "packaging\README_usage.txt") -Destination (Join-Path $AppDir "README.txt")

Write-Host ""
Write-Host "=== Build complete ===" -ForegroundColor Green
Write-Host "Output: $AppDir"
Write-Host "Double-click run.bat to start."
