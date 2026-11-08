"""Stores the Gemini API key in the OS password store (Windows Credential Manager / macOS Keychain)."""
import os

import keyring
from keyring.errors import KeyringError

SERVICE = "RJAC Invoice Renamer"
ACCOUNT = "gemini_api_key"


def get_api_key():
    """Environment variable (developer use) wins; otherwise the stored key, or None."""
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        return keyring.get_password(SERVICE, ACCOUNT)
    except KeyringError as e:
        print(f"Could not read API key from keychain: {e}")
        return None


def save_api_key(api_key):
    keyring.set_password(SERVICE, ACCOUNT, api_key.strip())


def delete_api_key():
    try:
        keyring.delete_password(SERVICE, ACCOUNT)
    except KeyringError:
        pass
