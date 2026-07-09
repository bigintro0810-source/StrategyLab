# Strategy Lab - distribution package build script
#
# Builds a self-contained, double-click-to-run distribution in dist\StrategyLab\.
#
# Uses "embeddable Python + pip install + batch launcher" instead of PyInstaller.
# Reason: api_server.py (and gui_app.py before it) launches main.py via
# subprocess.run([sys.executable, "main.py", ...]) (main.py's ProcessPoolExecutor
# uses Windows' "spawn" start method - running it in-process risks worker processes
# re-launching the server app itself, a known footgun). If frozen with PyInstaller,
# sys.executable would point back at the frozen exe itself, breaking that subprocess
# call. With an embedded Python, sys.executable correctly points at the bundled real
# python.exe, so the existing code works unmodified.
#
# The primary app is now the React+FastAPI web dashboard (api_server.py), which this
# script builds for production (`npm run build`) and bundles as static files served
# by api_server.py itself - end users never need Node.js installed, only this one
# process. The older Streamlit GUI (gui_app.py) is still copied in and can be run
# manually from the app folder for anyone who prefers it, but run.bat now launches
# the web dashboard as the primary experience.
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
Write-Host "[4/9] Installing dependencies (pandas/numpy/streamlit/fastapi/uvicorn/fpdf2/optuna)..."
Write-Host "  (this can take a few minutes)"
& "$PythonDir\python.exe" -m pip install --no-warn-script-location -r "$RepoRoot\requirements.txt"

# --- 5. Build the frontend for production ---
# Runs on THIS (build) machine only - end users never need Node.js, since
# the built static files (frontend/dist) are what gets shipped and served
# by api_server.py itself. Requires `npm install` to have been run once in
# frontend/ already (not re-run here to keep repeat builds fast).
Write-Host "[5/9] Building frontend (npm run build)..."
$FrontendDir = Join-Path $RepoRoot "frontend"
Push-Location $FrontendDir
try {
    npm run build
    if ($LASTEXITCODE -ne 0) {
        throw "frontend build failed (npm run build exited with code $LASTEXITCODE)"
    }
} finally {
    Pop-Location
}

# --- 6. Copy the application source ---
Write-Host "[6/9] Copying application files..."

$FilesToCopy = @(
    "main.py", "api_server.py", "gui_app.py", "walk_forward.py", "analyze_walk_forward.py",
    "analyze_monthly.py", "analyze_yearly.py", "analyze_stability.py",
    "analyze_sensitivity.py", "analyze_confidence.py", "compare_signals.py",
    "compare_tradingview.py", "equity_curve.py", "monte_carlo.py",
    "rerank_results.py", "rerun_ranking_row.py", "strategy_manager.py", "requirements.txt",
    "generate_pinescript.py", "import_broker_csv.py", "resample_timeframes.py"
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

# Only the built static output (frontend/dist) is needed at runtime -
# api_server.py mounts this directory directly, so the app folder doesn't
# need frontend/src, node_modules, package.json, etc.
$FrontendDistSrc = Join-Path $FrontendDir "dist"
$FrontendDistDest = Join-Path $AppSrcDir "frontend\dist"
New-Item -ItemType Directory -Force -Path (Join-Path $AppSrcDir "frontend") | Out-Null
Copy-Item $FrontendDistSrc -Destination $FrontendDistDest -Recurse

# --- 7. Create an empty data/raw folder with instructions ---
Write-Host "[7/9] Preparing data folder..."
$DataRawDir = Join-Path $AppSrcDir "data\raw"
New-Item -ItemType Directory -Force -Path $DataRawDir | Out-Null
Copy-Item (Join-Path $RepoRoot "packaging\data_raw_README.txt") -Destination (Join-Path $DataRawDir "README.txt")

# --- 8. Create run.bat ---
# Starts api_server.py in its own window (so its console/log output stays
# visible and closing that window is the documented way to stop the
# server), waits a few seconds for uvicorn to come up, then opens the
# dashboard in the default browser.
#
# The `start` window title is deliberately plain ASCII, not Japanese -
# on a real end-user machine, whether the system codepage is a legacy
# DBCS one (932/Shift-JIS) or the newer "Beta: Use Unicode UTF-8"
# system-wide setting determines how `Set-Content -Encoding Default`
# bytes get interpreted by cmd.exe when it parses this very line. A
# mismatch between the two (this build machine writes actual UTF-8 bytes
# under -Encoding Default, but cmd.exe's console codepage defaults to
# 932 unless the user has enabled that beta setting) corrupts the title
# into mojibake - and that corruption was observed to break `start`'s own
# argument parsing badly enough that it silently failed to launch
# python.exe at all (not just a cosmetic garbled title). ASCII sidesteps
# the whole codepage question rather than trying to get the encoding
# exactly right for every possible end-user locale configuration.
Write-Host "[8/9] Creating launcher..."
$RunBatContent = @'
@echo off
cd /d "%~dp0app"
start "Strategy Lab (close this window to stop)" "%~dp0python\python.exe" api_server.py
timeout /t 3 /nobreak >nul
start http://localhost:8736
'@
Set-Content -Path (Join-Path $AppDir "run.bat") -Value $RunBatContent -Encoding Default

# --- 9. Place end-user README / disclaimer ---
Write-Host "[9/9] Placing README..."
Copy-Item (Join-Path $RepoRoot "packaging\README_usage.txt") -Destination (Join-Path $AppDir "README.txt")

Write-Host ""
Write-Host "=== Build complete ===" -ForegroundColor Green
Write-Host "Output: $AppDir"
Write-Host "Double-click run.bat to start."
