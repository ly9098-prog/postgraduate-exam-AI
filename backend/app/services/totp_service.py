"""Time-based One-Time Password (RFC 6238 / RFC 4226) — stdlib only.

Implements TOTP verification for admin 2FA without adding a third-party
dependency. The algorithm is derived directly from the RFCs so it can be
tested against the published test vectors.

Backup codes are generated server-side and stored as bcrypt hashes via
``admin_security.hash_admin_password`` so a database dump never leaks the
plaintext codes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

from app.core.admin_security import hash_admin_password, verify_admin_password

# 6-digit codes, 30-second step (RFC 6238 defaults)
_TOTP_DIGITS = 6
_TOTP_STEP_SEC = 30
# Number of 30s steps of clock-skew tolerance in each direction
_DEFAULT_WINDOW = 1
_BACKUP_CODE_LENGTH = 10
_BACKUP_CODE_COUNT = 8


def _decode_base32(secret: str) -> bytes:
    """Decode an (upper/lower) base32 string to raw bytes, RFC 4648."""
    normalized = secret.strip().upper().replace(" ", "").replace("-", "")
    # Add padding so base64.b32decode accepts unpadded input.
    pad = "=" * ((8 - len(normalized) % 8) % 8)
    return base64.b32decode(normalized + pad, casefold=True)


def generate_totp_secret() -> str:
    """Generate a new base32 TOTP secret (20 random bytes = 160 bits)."""
    raw = secrets.token_bytes(20)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def otpauth_uri(secret: str, username: str, issuer: str = "MemoGrad Admin") -> str:
    """Build an otpauth:// provisioning URI for authenticator apps."""
    label = f"{issuer}:{username}"
    return (
        "otpauth://totp/"
        + _urlencode(label)
        + f"?secret={secret}&issuer={_urlencode(issuer)}"
        + f"&algorithm=SHA1&digits={_TOTP_DIGITS}&period={_TOTP_STEP_SEC}"
    )


def _urlencode(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def _hotp(secret: bytes, counter: int, digits: int = _TOTP_DIGITS) -> str:
    """RFC 4226 HOTP with SHA-1. Returns a zero-padded numeric string."""
    msg = struct.pack(">Q", counter)
    hs = hmac.new(secret, msg, hashlib.sha1).digest()
    offset = hs[-1] & 0x0F
    bin_code = (
        ((hs[offset] & 0x7F) << 24)
        | (hs[offset + 1] << 16)
        | (hs[offset + 2] << 8)
        | hs[offset + 3]
    )
    return str(bin_code % (10**digits)).zfill(digits)


def _totp_at(secret: str, timestamp: float, digits: int = _TOTP_DIGITS) -> str:
    """RFC 6238 code for a given Unix timestamp."""
    counter = int(timestamp // _TOTP_STEP_SEC)
    return _hotp(_decode_base32(secret), counter, digits)


def verify_totp(
    secret: str,
    code: str,
    *,
    window: int = _DEFAULT_WINDOW,
    now: float | None = None,
) -> bool:
    """Verify a 6-digit TOTP code within ±window steps of the current time.

    Comparison is constant-time (``hmac.compare_digest``) to avoid timing
    side channels.
    """
    candidate = (code or "").strip()
    if not candidate.isdigit() or len(candidate) != _TOTP_DIGITS:
        return False
    if not secret:
        return False
    timestamp = now if now is not None else time.time()
    current = int(timestamp // _TOTP_STEP_SEC)
    expected = _decode_base32(secret)
    for counter in range(current - window, current + window + 1):
        if hmac.compare_digest(candidate, _hotp(expected, counter)):
            return True
    return False


def generate_backup_codes(count: int = _BACKUP_CODE_COUNT) -> list[str]:
    """Generate ``count`` one-time backup codes (10-char base32-ish tokens)."""
    codes: list[str] = []
    seen: set[str] = set()
    while len(codes) < count:
        token = secrets.token_hex(6).upper()[: _BACKUP_CODE_LENGTH]
        if token not in seen:
            seen.add(token)
            codes.append(token)
    return codes


def hash_backup_code(code: str) -> str:
    return hash_admin_password(code)


def verify_backup_code(code: str, hashes: list[str]) -> tuple[bool, list[str]]:
    """Verify a backup code against bcrypt hashes.

    Returns ``(matched, remaining_hashes)``. On a match the consumed hash is
    removed so the code can be marked single-use by the caller.
    """
    candidate = (code or "").strip().upper()
    if not hashes or not candidate:
        return False, hashes
    remaining = list(hashes)
    for i, digest in enumerate(hashes):
        try:
            if verify_admin_password(candidate, digest):
                remaining.pop(i)
                return True, remaining
        except ValueError:
            # Overlong/invalid stored hash — treat as non-matching.
            continue
    return False, hashes
