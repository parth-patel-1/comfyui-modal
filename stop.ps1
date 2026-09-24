# Stops the deployed ComfyUI app on Modal (stops GPU billing; the web URL
# goes offline until you run launch.ps1 again). Model files stored in the
# Modal volumes are kept.
#
# Usage:  .\stop.ps1 [-Profile NAME]   stop the app in a specific Modal account

param(
    [string]$Profile   # optional: Modal account/profile the app runs in
)

$AppDir = $PSScriptRoot
Set-Location $AppDir

if ($Profile) { $env:MODAL_PROFILE = $Profile }

$Py = "$AppDir\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

Write-Host "Stopping Modal app 'comfyui-hosting' ..."
& $Py -m modal app stop comfyui-hosting -y
Write-Host "Done. Your ComfyUI URL is offline and billing has stopped."
Write-Host "Re-launch any time with: .\launch.ps1"
