"""Five smoke tests that prove the security core is real, not aspirational.

Run them before you build:  uv run pytest -q

  1. imports          — the security core (auth, session) loads
  2. valid token      — a good token resolves its subject
  3. failing-auth     — a token for ANOTHER server is rejected (audience binding works)
  4. isolation        — each verified subject keys only to itself (no cross-user leak)
  5. no-session       — a call with no session token is refused (fail closed)

These run offline (no database, no network, no FastMCP). They cover the two files that ship
complete — `auth.py` and `session.py` — the parts you must NOT regenerate. Everything else
(the gateway, the two-table store, the domain tools) you build through the course, and verify
live: end-to-end state isolation against a real Neon database happens in the capstone.
"""

import time
from typing import Any
from collections.abc import Callable

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from jose.utils import long_to_base64

from connector_app import auth, session


@pytest.fixture
def make_token() -> Callable[..., str]:
    """Mint RS256 tokens signed by a throwaway key the validator will trust."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key().public_numbers()
    pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    # Seed the JWKS cache so auth.py verifies against our throwaway key with no network call.
    auth._jwks_cache = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "test-kid",
                "n": long_to_base64(pub.n).decode(),
                "e": long_to_base64(pub.e).decode(),
            }
        ]
    }
    auth._jwks_fetched_at = time.time()

    def _make(sub: str, aud: str = auth.RESOURCE_URL) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": auth.AUTH_ISSUER,
            "sub": sub,
            "aud": aud,
            "iat": now,
            "exp": now + 3600,
        }
        return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": "test-kid"})

    return _make


def test_package_imports() -> None:
    # The security core ships complete; the gateway/server is what you build, so it's not here yet.
    assert hasattr(auth, "verified_claims")
    assert hasattr(session, "require_session")


def test_valid_token_resolves_subject(make_token: Callable[..., str]) -> None:
    assert auth.verified_claims(make_token("user-A"))["sub"] == "user-A"


def test_wrong_audience_is_rejected(make_token: Callable[..., str]) -> None:
    # FAILING-AUTH: a token minted for a different server must be refused (RFC 8707).
    with pytest.raises(auth.AuthError):
        auth.verified_claims(make_token("user-A", aud="http://evil.example"))


def test_identity_isolation(make_token: Callable[..., str]) -> None:
    # CROSS-USER ISOLATION: identity comes from the token's sub; A and B never cross.
    a_sub, a_role = session.require_session(
        session.new_session_token(auth.verified_claims(make_token("user-A"))["sub"])
    )
    b_sub, b_role = session.require_session(
        session.new_session_token(auth.verified_claims(make_token("user-B"))["sub"])
    )
    assert a_sub == "user-A" and b_sub == "user-B" and a_sub != b_sub
    assert a_role is None and b_role is None


def test_no_session_is_refused() -> None:
    # FAIL CLOSED: a call with no session token is rejected.
    with pytest.raises(session.SessionError):
        session.require_session("")


def test_require_role_gates_access(make_token: Callable[..., str]) -> None:
    # A token with no role should be denied by require_role for any specific role
    sub = auth.verified_claims(make_token("user-A"))["sub"]
    token_no_role = session.new_session_token(sub)
    assert session.require_role(token_no_role, ["admin"]) is None
    assert session.require_role(token_no_role, ["staff"]) is None

    # A token with a role should be allowed for that role
    token_admin = session.new_session_token(sub, role="admin")
    assert session.require_role(token_admin, ["admin"]) == "user-A"
    assert session.require_role(token_admin, ["staff"]) is None

    token_staff = session.new_session_token(sub, role="staff")
    assert session.require_role(token_staff, ["admin", "staff"]) == "user-A"
    assert session.require_role(token_staff, ["admin"]) is None


def test_role_is_none_by_default(make_token: Callable[..., str]) -> None:
    # Backward compat: existing session tokens have no role claim
    sub = auth.verified_claims(make_token("user-bob"))["sub"]
    token = session.new_session_token(sub)
    _, role = session.require_session(token)
    assert role is None


def test_role_is_stored_in_token(make_token: Callable[..., str]) -> None:
    # A role claim should be preserved in the session token
    sub = auth.verified_claims(make_token("user-alice"))["sub"]
    token = session.new_session_token(sub, role="admin")
    _, role = session.require_session(token)
    assert role == "admin"
