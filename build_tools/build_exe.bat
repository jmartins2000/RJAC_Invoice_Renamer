@echo off
echo ====================================
echo Building RJAC Invoice Renamer .exe
echo ====================================

echo.
echo [1/3] Preparing icon...
python build_tools\prepare_icon.py

echo.
echo [2/3] Cleaning old build artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist *.spec del /q *.spec

echo.
echo [3/3] Building executable with PyInstaller...
pyinstaller --onefile --windowed --icon=assets\logo.ico --name "RJAC_Invoice_Renamer" --add-data "assets;assets" main.py

echo.
echo ====================================
echo Build complete!
echo Executable: dist\RJAC_Invoice_Renamer.exe
echo ====================================
pause

