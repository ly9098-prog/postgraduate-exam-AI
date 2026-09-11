"""Secure secret encryption/decryption — Fernet with versioned envelope format.

Format: ``enc:v1:<fernet-token>``

Uses ``cryptography.fernet.Fernet`` — never implement custom crypto.
"""

from __future__ import annotations

import dataclasses
import re

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

ENCRYPTED_PREFIX = "enc:v1:"
_ALLOWED_PREFIXES = {"enc:v1:"}

# Sensitive field patterns used for audit log sanitisation
SENSITIVE_FIELD_PATTERNS: list[re.Pattern] = [
    re.compile(r"^api_key$", re.IGNORECASE),
    re.compile(r"^api_key_encrypted$", re.IGNORECASE),
    re.compile(r"^embedding_api_key$", re.IGNORECASE),
    re.compile(r"^embedding_api_key_encrypted$", re.IGNORECASE),
    re.compile(r"^proxy_authorization$", re.IGNORECASE),
    re.compile(r"^access_token$", re.IGNORECASE),
    re.compile(r"^refresh_token$", re.IGNORECASE),
    re.compile(r"^password(_hash)?$", re.IGNORECASE),
    re.compile(r"^secret$", re.IGNORECASE),
    re.compile(r"authorization$", re.IGNORECASE),
]

# Mask placeholder values that must never be stored as real credentials
MASK_PLACEHOLDER_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\*{4,}$"),  # 4+ asterisks
    re.compile(r"^\s*\*{4,}\s*$"),  # with surrounding whitespace
]


class SecretEncryptionError(RuntimeError):
    """Encryption failed (key missing, invalid, or operation error).

    The message is safe for logs — it never contains the plaintext or key.
    """


class SecretDecryptionError(RuntimeError):
    """Decryption failed (key mismatch, corrupted data, unsupported format).

    The message is safe for logs — it never contains the ciphertext or key.
    """


class SecretEnvelopeVersionError(RuntimeError):
    """The envelope version is unknown or unsupported."""


@dataclasses.dataclass(frozen=True)
class SecretEnvelope:
    """Parsed secret envelope."""

    raw: str
    version: str  # "v1"
    token: str  # payload inside envelope


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_fernet() -> Fernet:
    """Get a Fernet instance; raise SecretEncryptionError on missing/invalid."""
    key = settings.AI_CONFIG_ENCRYPT_KEY
    if not key:
        raise SecretEncryptionError(
            "AI_CONFIG_ENCRYPT_KEY not configured — cannot encrypt or decrypt."
        )
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise SecretEncryptionError(f"AI_CONFIG_ENCRYPT_KEY is invalid: {exc}") from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encrypt_secret(plaintext: str) -> str:
    """Encrypt *plaintext* and return ``enc:v1:<fernet-token>``.

    Raises:
        SecretEncryptionError: key missing, invalid, or encryption failed.
    """
    if not plaintext:
        raise SecretEncryptionError("Cannot encrypt empty value")

    f = _require_fernet()
    try:
        token = f.encrypt(plaintext.encode()).decode()
    except Exception as exc:
        raise SecretEncryptionError(f"Encryption failed: {exc}") from exc

    return f"{ENCRYPTED_PREFIX}{token}"


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a versioned envelope to plaintext.

    Raises:
        SecretDecryptionError: unsupported format, wrong key, corrupted data.
    """
    if not ciphertext:
        raise SecretDecryptionError("No secret to decrypt — value is empty.")

    try:
        envelope = parse_secret_envelope(ciphertext)
    except SecretEnvelopeVersionError as exc:
        raise SecretDecryptionError(str(exc)) from exc
    except ValueError as exc:
        raise SecretDecryptionError(str(exc)) from exc

    if envelope.version != "v1":
        raise SecretDecryptionError(
            f"Unsupported encryption version '{envelope.version}' — "
            "only 'v1' is supported."
        )

    if not envelope.token:
        raise SecretDecryptionError("Encrypted secret envelope is empty or malformed.")

    f = _require_fernet()
    try:
        return f.decrypt(envelope.token.encode()).decode()
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "Failed to decrypt secret — the encryption key may have been "
            "rotated or the data is corrupted."
        ) from exc
    except Exception as exc:
        raise SecretDecryptionError(f"Decryption failed: {exc}") from exc


def is_encrypted_secret(value: str) -> bool:
    """Check whether *value* has a recognised encrypted envelope prefix."""
    return bool(value and value.startswith("enc:v1:"))


def parse_secret_envelope(value: str) -> SecretEnvelope:
    """Parse a secret envelope string into its components.

    Returns:
        A ``SecretEnvelope`` with version and token.

    Raises:
        ValueError: value is empty.
        SecretEnvelopeVersionError: ``enc:`` prefix but unknown version.
    """
    if not value:
        raise ValueError("Cannot parse empty value")

    if not value.startswith("enc:"):
        # Not an envelope at all — the caller decides how to handle this.
        raise ValueError(
            "Value is not a recognised encrypted envelope. "
            "Plain-text secrets must be migrated before use."
        )

    # Strip "enc:" prefix
    rest = value[4:]
    if not rest:
        raise SecretEnvelopeVersionError(
            "Encrypted envelope has no version — malformed value."
        )

    parts = rest.split(":", 1)
    version = parts[0]
    token = parts[1] if len(parts) > 1 else ""

    if version not in ("v1",):  # extend here when new versions are added
        raise SecretEnvelopeVersionError(
            f"Unsupported encryption version '{version}' — supported versions: v1"
        )

    return SecretEnvelope(raw=value, version=version, token=token)


def is_mask_placeholder(value: str | None) -> bool:
    """Check if *value* is a recognised mask placeholder (e.g. ``****``)."""
    if not value:
        return False
    return any(p.match(value) for p in MASK_PLACEHOLDER_PATTERNS)


def is_sensitive_field(field_name: str) -> bool:
    """Check if *field_name* should be sanitised in logs/audit."""
    return any(p.match(field_name) for p in SENSITIVE_FIELD_PATTERNS)


def sanitise_dict(value: object) -> object:
    """Recursively sanitise sensitive fields in a nested dict/list structure.

    Sensitive field values are replaced with ``[REDACTED]``.
    """
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if is_sensitive_field(str(k)) else sanitise_dict(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitise_dict(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitise_dict(item) for item in value)
    return value
