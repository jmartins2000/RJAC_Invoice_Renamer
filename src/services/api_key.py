"""The Gemini API key, kept in a small file in the app's data folder (readable only by this user).

Earlier versions used the OS keychain; on macOS that asks for approval again after every update
(unsigned builds), which isn't worth it for an API key. A key found there is moved to the file once.
"""
import json
import os

_cached = None


def _path():
    from src.services.settings import _dir
    return os.path.join(_dir(), "api_key.json")


def _read_file():
    try:
        with open(_path(), encoding="utf-8") as f:
            return (json.load(f).get("gemini_api_key") or "").strip() or None
    except (OSError, ValueError):
        return None


def _write_file(key):
    path = _path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"gemini_api_key": key}, f)
    try:
        os.chmod(tmp, 0o600)  # owner only (no effect on Windows, where the profile folder is private)
    except OSError:
        pass
    os.replace(tmp, path)


def _from_old_keychain():
    """One-time move from the keychain used by earlier versions."""
    try:
        import keyring
        return keyring.get_password("RJAC Invoice Renamer", "gemini_api_key")
    except Exception:
        return None


def get_api_key():
    """Environment variable (developer use) wins; otherwise the saved key, or None."""
    global _cached
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    if _cached:
        return _cached
    _cached = _read_file()
    if not _cached:
        old = _from_old_keychain()
        if old:
            _write_file(old.strip())
            _cached = old.strip()
    return _cached


def save_api_key(api_key):
    global _cached
    _write_file(api_key.strip())
    _cached = api_key.strip()


def delete_api_key():
    global _cached
    _cached = None
    try:
        os.remove(_path())
    except OSError:
        pass
