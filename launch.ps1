# ComfyUI on Modal -- one-click launcher for Windows.
#
# Usage (from an ordinary PowerShell window):
#   .\launch.ps1                                      full launch: setup, model download, deploy, open website
#   .\launch.ps1 -TokenId ak-... -TokenSecret as-...  authenticate with a Modal API token (non-interactive)
#   .\launch.ps1 -SkipModels                          skip the one-time model pre-download
#   .\launch.ps1 -NoBrowser                           deploy but do not open the browser
#   .\launch.ps1 -Profile NAME                        deploy into a specific Modal account/profile
#
# Requirements: Python 3.9+ on PATH (https://python.org) and a free Modal account
# (https://modal.com). Authentication uses a Modal API token ID + secret
# (pass -TokenId/-TokenSecret, or set MODAL_TOKEN_ID/MODAL_TOKEN_SECRET); if none
# are provided, a one-time browser sign-in opens on first launch.

param(
    [string]$Profile,
    [string]$TokenId,      # Modal API token ID (ak-...) for non-interactive auth
    [string]$TokenSecret,  # Modal API token secret (as-...)
    [switch]$SkipModels,
    [switch]$NoBrowser
)

$AppDir = $PSScriptRoot
Set-Location $AppDir

# The Modal CLI prints Unicode (e.g. checkmarks). When its output is redirected
# (as in the deploy step below), Python on Windows defaults to the 'charmap'
# codec and crashes; force UTF-8 so that cannot happen.
$env:PYTHONIOENCODING = "utf-8"

# Target a specific Modal account (profile) for this launch -- see README,
# "Multiple Modal accounts". Applies to every modal command below.
if ($Profile) { $env:MODAL_PROFILE = $Profile }

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# --- 1. Python virtual environment with the Modal CLI ------------------------
Step "Setting up Python environment"
if (-not (Test-Path "$AppDir\.venv")) {
    python -m venv "$AppDir\.venv"
    if ($LASTEXITCODE -ne 0) {
        throw "Python not found. Install Python 3.9+ from https://python.org, then re-run this script."
    }
}
$Py = "$AppDir\.venv\Scripts\python.exe"
& $Py -m pip install --quiet --upgrade pip
& $Py -m pip install --quiet -r "$AppDir\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "Failed to install the 'modal' package. Check your internet connection." }
Write-Host "Environment ready."

# --- 2. Modal authentication (token ID + secret preferred) ---------------------
Step "Checking Modal authentication"
if (-not $TokenId)     { $TokenId     = $env:MODAL_TOKEN_ID }
if (-not $TokenSecret) { $TokenSecret = $env:MODAL_TOKEN_SECRET }

if ($TokenId -and $TokenSecret) {
    Write-Host "Authenticating with Modal token ID + secret ..."
    # Env vars make every modal command below use these credentials (they take
    # precedence over ~/.modal.toml).
    $env:MODAL_TOKEN_ID = $TokenId
    $env:MODAL_TOKEN_SECRET = $TokenSecret
    # Also persist the credentials so stop.ps1 and future launches work too.
    & $Py -m modal token set --token-id $TokenId --token-secret $TokenSecret --verify
    if ($LASTEXITCODE -ne 0) { throw "Modal token authentication failed. Check the token ID and token secret." }
} else {
    & $Py -m modal app list *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "No Modal credentials found. Starting 'modal token new' ..."
        Write-Host "A browser window will open -- sign in (or create a free account) at modal.com."
        & $Py -m modal token new
        if ($LASTEXITCODE -ne 0) { throw "Modal authentication failed. Re-run this script to try again." }
    } else {
        Write-Host "Already authenticated with Modal."
    }
}

# --- 3. Pre-download models (one-time, ~24 GB for the default Qwen-Image-2.1 set) ---
if (-not $SkipModels) {
    Step "Downloading default models into the Modal volume (one-time)"
    & $Py -m modal run "$AppDir\comfyui_app.py"
    if ($LASTEXITCODE -ne 0) { throw "Model download failed. See the output above for the cause." }
} else {
    Write-Host "Skipping model pre-download (-SkipModels)."
}

# --- 4. Deploy the persistent web app ------------------------------------------
Step "Deploying ComfyUI web app to Modal (first build takes a few minutes)"
$DeployOutput = (& $Py -m modal deploy "$AppDir\comfyui_app.py" 2>&1 | Out-String)
Write-Host $DeployOutput
if ($LASTEXITCODE -ne 0) { throw "Deploy failed. See the output above." }

# --- 5. Open the website --------------------------------------------------------
$UrlMatches = [regex]::Matches($DeployOutput, "https://[a-zA-Z0-9\-\.]+\.modal\.run")
if ($UrlMatches.Count -gt 0) {
    $Url = $UrlMatches[$UrlMatches.Count - 1].Value
    Write-Host "`nComfyUI is live at: $Url" -ForegroundColor Green
    Write-Host "First load may take up to ~1 minute (cold start of the GPU container)."
    Write-Host "Stop GPU billing when you're done:  .\stop.ps1"
    if (-not $NoBrowser) { Start-Process $Url }
} else {
    Write-Warning "Could not parse the web URL from the deploy output -- find it above, or run: modal app list"
}
