"""Stores the Gemini API key in the OS password store (Windows Credential Manager / macOS Keychain)."""
import os

import keyring
from keyring.errors import KeyringError

SERVICE = "RJAC Invoice Renamer"
ACCOUNT = "gemini_api_key"

# Read the keychain once per launch: every read can trigger a macOS permission prompt.
_cached = None


def get_api_key():
    """Environment variable (developer use) wins; otherwise the stored key, or None."""
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    global _cached
    if _cached:
        return _cached
    try:
        _cached = keyring.get_password(SERVICE, ACCOUNT)
        return _cached
    except KeyringError as e:
        print(f"Could not read API key from keychain: {e}")
        return None


def save_api_key(api_key):
    global _cached
    keyring.set_password(SERVICE, ACCOUNT, api_key.strip())
    _cached = api_key.strip()


def delete_api_key():
    global _cached
    _cached = None
    try:
        keyring.delete_password(SERVICE, ACCOUNT)
    except KeyringError:
        pass
