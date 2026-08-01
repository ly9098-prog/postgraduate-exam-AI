"""Tests for the admin password strength policy (admin_security.py)."""

from __future__ import annotations

import pytest

from app.core.admin_security import (
    PasswordPolicyError,
    validate_admin_password_strength,
)


def test_accepts_strong_password():
    validate_admin_password_strength("Str0ngPassw0rd!")  # must not raise


@pytest.mark.parametrize(
    ("weak", "expected_message"),
    [
        ("short1A", "长度"),           # 7 chars < 12
        ("lowercasepassword1", "大写"),  # no uppercase
        ("UPPERCASEPASSWORD1", "小写"),  # no lowercase
        ("NoDigitsHereAa", "数字"),      # no digit
    ],
)
def test_rejects_weak_password(weak, expected_message):
    with pytest.raises(PasswordPolicyError) as exc:
        validate_admin_password_strength(weak)
    assert expected_message in str(exc.value)


def test_rejects_exactly_at_min_length_without_uppercase():
    # 12 chars but no uppercase letter.
    with pytest.raises(PasswordPolicyError):
        validate_admin_password_strength("lowercase12ab")
