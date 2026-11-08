# Builds the app folder with PyInstaller and the installer with Inno Setup.
# Needs: Python with requirements.txt installed, Inno Setup 6 (iscc on PATH).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$version = (Select-String -Path src\version.py -Pattern '__version__ = "(.+?)"').Matches[0].Groups[1].Value

python build_tools\prepare_icon.py
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path "dist\RJAC Invoice Renamer") { Remove-Item -Recurse -Force "dist\RJAC Invoice Renamer" }
pyinstaller --noconfirm --distpath dist --workpath build build_tools\rjac.spec

iscc /DAppVersion=$version build_tools\windows_installer.iss
Write-Host "Built: dist\RJAC-Invoice-Renamer-Setup-$version.exe"
