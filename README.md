# RJAC Invoice Renamer

Desktop app (Windows and macOS) that reads invoice PDFs with Google Gemini and renames them to
`<date> <total> <invoice number> <supplier>_<original name>.pdf`, with a review screen to check
and correct every value before anything is renamed. It can also export the values to Excel.

## For users

**Install**
- **Windows:** download `RJAC-Invoice-Renamer-Setup-<version>.exe` from the latest release and run it.
  No admin rights needed. If Windows shows "Windows protected your PC", click **More info → Run anyway**
  (the app isn't code-signed).
- **macOS:** open `RJAC-Invoice-Renamer-<version>-mac.dmg` and drag the app into Applications.
  The first time, right-click the app → **Open** (it isn't notarized by Apple).

**First launch:** the app asks for a Gemini API key (get one at https://aistudio.google.com/apikey).
It is checked and saved in the app's data folder for that user only (never inside the app itself),
so there are no password prompts. Change it any time under **Settings**.

**How it works:** pick a folder, check the values Gemini read for each invoice, then rename them all.
Invoices are remembered in a local **History** (by file contents), so reopening a folder or renamed files
costs nothing. In **History** you can filter by quarter/year or folder and export to Excel, or build an
Excel from any folder ("Excel from a folder"). Under **Settings → Fields** you choose what is read
(e.g. NIF, VAT) and what goes into the filename and the Excel; the filename separator defaults to ` ~ `.

**Updates:** the app checks for a new version on startup and offers **Update now**. On Windows it installs
and reopens by itself. On macOS it opens the new .dmg so you can replace the app.

## For developers

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements.txt
echo "GEMINI_API_KEY=..." > .env      # dev only, gitignored, never bundled
.venv/bin/python main.py
```

**Model choice / accuracy:** `tools/eval_extraction.py` runs extraction on `samples/` (gitignored, real
invoices) against `samples/ground_truth.json`, e.g. `python tools/eval_extraction.py --model gemini-3.8-flash`.
`--legacy` runs the original v1 code as a baseline. The model is set by `DEFAULT_MODEL` in
`src/services/gemini_service.py` (override with `RJAC_MODEL` env var).

**Releasing a new version**
1. Bump `__version__` in `src/version.py`.
2. Commit, then tag and push: `git tag v2.0.1 && git push origin main v2.0.1`.
3. GitHub Actions (`.github/workflows/release.yml`) builds the Windows installer and the macOS .dmg,
   smoke-tests the Windows build, and publishes them as a GitHub Release. Installed apps pick it up
   on their next start.

The tag must match `__version__`. Update checks read the repo's public Releases
(`GITHUB_REPO` in `src/version.py`), so the releases must be publicly readable.

**Local builds:** `./build_tools/build_mac.sh` (macOS) or `build_tools\build_windows.ps1` (Windows, needs
Inno Setup 6). Output goes to `dist/`.
