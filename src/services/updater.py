"""Checks GitHub Releases for a newer version and installs it.

Release assets are expected to follow these names (produced by .github/workflows/release.yml):
  Windows: RJAC-Invoice-Renamer-Setup-<version>.exe   (Inno Setup installer)
  macOS:   RJAC-Invoice-Renamer-<version>-mac.dmg
"""
import os
import subprocess
import sys
import tempfile

import requests
from packaging.version import InvalidVersion, Version

from src.version import GITHUB_REPO, __version__

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


class UpdateInfo:
    def __init__(self, version, notes, page_url, asset_url, asset_name):
        self.version = version
        self.notes = notes
        self.page_url = page_url
        self.asset_url = asset_url
        self.asset_name = asset_name


def _asset_suffix():
    if sys.platform == "win32":
        return ".exe"
    if sys.platform == "darwin":
        return "-mac.dmg"
    return None


def check_for_update(current=__version__, timeout=6):
    """Returns UpdateInfo if a newer release exists, else None. Never raises."""
    try:
        r = requests.get(API_URL, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            return None
        rel = r.json()
        latest = Version(rel.get("tag_name", "").lstrip("vV"))
        if latest <= Version(current):
            return None
        suffix = _asset_suffix()
        asset = next(
            (a for a in rel.get("assets", []) if suffix and a["name"].endswith(suffix)), None
        )
        return UpdateInfo(
            version=str(latest),
            notes=(rel.get("body") or "").strip(),
            page_url=rel.get("html_url"),
            asset_url=asset["browser_download_url"] if asset else None,
            asset_name=asset["name"] if asset else None,
        )
    except (requests.RequestException, InvalidVersion, ValueError, KeyError) as e:
        print(f"Update check failed: {e}")
        return None


def list_releases(timeout=8):
    """Every published release with an installer for this computer, newest first. [] if offline."""
    try:
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=50", timeout=timeout,
                         headers={"Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            return []
        suffix = _asset_suffix()
        out = []
        for rel in r.json():
            if rel.get("draft") or rel.get("prerelease"):
                continue
            try:
                v = Version(rel.get("tag_name", "").lstrip("vV"))
            except InvalidVersion:
                continue
            asset = next((a for a in rel.get("assets", []) if suffix and a["name"].endswith(suffix)), None)
            if not asset:
                continue
            info = UpdateInfo(str(v), (rel.get("body") or "").strip(), rel.get("html_url"),
                              asset["browser_download_url"], asset["name"])
            info.date = (rel.get("published_at") or "")[:10]
            out.append(info)
        return sorted(out, key=lambda i: Version(i.version), reverse=True)
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"Couldn't list releases: {e}")
        return []


def download(info, progress=None):
    """Downloads the installer to a temp folder. progress(fraction) is called as it goes."""
    dest = os.path.join(tempfile.mkdtemp(prefix="rjac-update-"), info.asset_name)
    with requests.get(info.asset_url, stream=True, timeout=30) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done / total)
    return dest


def launch_installer(path):
    """Starts the installer. On Windows the app must exit right after so files can be replaced."""
    if sys.platform == "win32":
        # Inno Setup: install silently, close the running app, then relaunch it (see installer .iss).
        subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS", "/NORESTART"],
                         close_fds=True)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
