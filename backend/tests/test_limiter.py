"""Rate-limit key selection: per-user when authenticated, per-IP otherwise."""

from __future__ import annotations

from starlette.requests import Request

from src.auth.utils import create_access_token
from src.limiter import rate_limit_key


def _request(authorization: str | None = None) -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return Request(
        {
            "type": "http",
            "headers": headers,
            "client": ("203.0.113.7", 1234),
            "method": "GET",
            "path": "/",
            "query_string": b"",
        }
    )


def test_authenticated_requests_key_on_user():
    token, _ = create_access_token("user-123")
    assert rate_limit_key(_request(f"Bearer {token}")) == "user:user-123"


def test_anonymous_and_invalid_tokens_key_on_ip():
    assert rate_limit_key(_request()) == "203.0.113.7"
    assert rate_limit_key(_request("Bearer garbage")) == "203.0.113.7"
