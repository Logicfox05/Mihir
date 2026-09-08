"""Encrypts connection passwords (API keys, Dropbox tokens) before they are stored in the database.

The key comes from SECRET_KEY in .env. If that is not set, a key is generated once into
backend/.secret_key (git-ignored) so the feature works without extra setup. Losing the key only
means the saved passwords must be entered again - nothing else is affected.
"""
from __future__ import annotations

import base64
import hashlib

import structlog
from cryptography.fernet import Fernet, InvalidToken

from ..config import BACKEND_DIR, get_settings

log = structlog.get_logger(__name__)
KEY_FILE = BACKEND_DIR / ".secret_key"
PREFIX = "enc:"


def _fernet() -> Fernet:
    passphrase = get_settings().secret_key.strip()
    if passphrase:
        # any passphrase is accepted; a real Fernet key is derived from it
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(passphrase.encode("utf-8")).digest()))
    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(Fernet.generate_key())
        log.info("secret_key_file_created", path=str(KEY_FILE))
    return Fernet(KEY_FILE.read_bytes().strip())


def encrypt(value: str) -> str:
    if not value:
        return ""
    return PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str) -> str:
    """Returns "" if the value cannot be decrypted (e.g. the key changed) - never raises."""
    if not value:
        return ""
    if not value.startswith(PREFIX):
        return value  # written before encryption was in place
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as e:
        log.warning("secret_decrypt_failed", error=str(e))
        return ""


def mask(value: str) -> str:
    """What the browser is allowed to see."""
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 8 else "••••"
