"""HTTP access policy for detailed runtime metrics."""

import hmac

from fastapi import HTTPException, Request


def require_observability_access(
    request: Request, *, production_mode: bool, token: str,
) -> None:
    """Protect detailed runtime metrics in restricted environments.

    Local development remains convenient. In cloud/production a blank token
    disables the endpoint (404); otherwise clients must send
    ``Authorization: Bearer <OBSERVABILITY_TOKEN>``.
    """
    if not production_mode:
        return
    expected = (token or "").strip()
    authorization = request.headers.get("authorization", "")
    scheme, _, supplied = authorization.partition(" ")
    if (
        not expected
        or scheme.lower() != "bearer"
        or not supplied
        or not hmac.compare_digest(supplied, expected)
    ):
        # Hide the existence of the diagnostics endpoint from unauthenticated
        # internet scanners rather than advertising an auth-protected target.
        raise HTTPException(status_code=404, detail="Not Found")
