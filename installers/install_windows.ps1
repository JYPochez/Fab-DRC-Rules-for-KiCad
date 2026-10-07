# SPDX-License-Identifier: GPL-3.0-or-later
# Installs the Fab DRC Rules plugin for KiCad on Windows.
#   .\install_windows.ps1                  install for KiCad 10.0
#   .\install_windows.ps1 -Version 9.0     install for another KiCad version
#   .\install_windows.ps1 -Uninstall       remove it
# If scripts are blocked, run install_windows.bat instead.
param(
    [string]$Version = "10.0",
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"

$Plugin = "fab_drc_rules"
$Source = Join-Path (Split-Path -Parent $PSScriptRoot) $Plugin
# MyDocuments follows a OneDrive-redirected Documents folder, as KiCad does.
$Documents = [Environment]::GetFolderPath("MyDocuments")
$TargetDir = Join-Path $Documents "KiCad\$Version\scripting\plugins"
$Target = Join-Path $TargetDir $Plugin

if ($Uninstall) {
    if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
    Write-Host "Removed $Target"
    exit 0
}

if (-not (Test-Path (Join-Path $Source "__init__.py"))) {
    Write-Error "Plugin source not found: $Source"
}
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

# Keep the user's saved choices across updates.
$Saved = $null
$SettingsFile = Join-Path $Target "settings.json"
if (Test-Path $SettingsFile) { $Saved = Get-Content -Raw $SettingsFile }

if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
Copy-Item -Recurse $Source $Target
foreach ($junk in @("__pycache__", "settings.json", ".DS_Store")) {
    $path = Join-Path $Target $junk
    if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}
if ($null -ne $Saved) { Set-Content -NoNewline -Path $SettingsFile -Value $Saved }

Write-Host "Installed in $Target"
Write-Host "In the PCB editor: Tools > External Plugins > Refresh Plugins (or restart KiCad)."
