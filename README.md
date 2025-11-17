# RJAC Invoice Renamer

A Python application for renaming invoices.

## Running the Application

```bash
python main.py
```

## Requirements

- Python 3.x (tkinter is included by default)

## Building an Executable

### Prerequisites

Install dependencies (including PyInstaller):
```bash
pip install -r requirements.txt
```

### Build

Run the build script from the project root:
```bash
build_tools\build_exe.bat
```

This will:
1. Prepare the icon (remove white background, round corners, convert to .ico)
2. Clean old build artifacts
3. Build the executable with PyInstaller

The executable will be in the `dist\` folder as `RJAC_Invoice_Renamer.exe`.

