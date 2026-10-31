"""OAuth 2.1 Authorization Server for StockLens MCP.

Implements RFC 8414 (AS metadata), RFC 9728 (Protected Resource metadata),
RFC 7636 PKCE S256, and RFC 7517 JWKS (RS256) on top of the existing JWT infra.
Auth codes live in Redis (TTL 600s), reuse create_access_token +
refresh_tokens table. RS256 is the default for MCP — HS256 fallback kept for
legacy REST clients. MCP Authorization spec 2026-07-28 add-ons: RFC 9207
issuer validation (iss in authorization responses) and CIMD
(draft-ietf-oauth-client-id-metadata-document) client registration.

Enterprise upgrade over LAAD's unauthenticated stdio:
  • Authorization Code + PKCE (S256) + RS256/JWKS + kid rotation
  • Refresh rotation with stolen-token revoke-all
  • CIMD registration with SSRF guard + redirect_uri enforcement
  • RFC 9207 iss on authorization responses
  • WWW-Authenticate with resource_metadata + scope guidance

Endpoints:
  GET  /.well-known/oauth-authorization-server
  GET  /.well-known/oauth-protected-resource
  GET  /.well-known/jwks.json               (RS256 public keys)
  GET  /oauth/authorize  (browser)
  POST /oauth/authorize  (Inspector JSON flow)
  POST /oauth/token
  POST /oauth/revoke
  POST /oauth/register
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import secrets
import socket
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

import jwt as pyjwt
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

# RS256 — optional, graceful fallback to HS256 (cryptography already in deps via authlib)
try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    _CRYPTO_AVAILABLE = True
except Exception:  # pragma: no cover
    _CRYPTO_AVAILABLE = False

from src.auth.schemas import TokenPayload
from src.auth.utils import (
    create_refresh_token,
    decode_token,
    hash_token,
    verify_password,
)
from src.cache.redis import get_redis, is_token_blacklisted
from src.config import settings
from src.database.connection import connection_ctx
from src.limiter import limiter

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["mcp-oauth"])

# ponytail: reuse existing bearer extractor so MCP and REST share semantics
_mcp_security = HTTPBearer(auto_error=False)

# ── Helpers ───────────────────────────────────────────────────────────────


# Environments where deriving the OAuth issuer from the request Host header is
# acceptable. Deployed environments must set OAUTH_ISSUER: the Host header is
# client-controlled, so deriving the issuer from it lets an attacker poison the
# advertised issuer + metadata behind a misconfigured proxy.
_DEV_ENVIRONMENTS = frozenset({"development", "dev", "test"})


def _issuer(request: Request) -> str:
    """Return the OAuth issuer — configured value, else request-derived (dev).

    Priority: OAUTH_ISSUER env → request.base_url (scheme+host).
    Trailing slash stripped for RFC 8414 compliance. In a deployed environment
    an unset OAUTH_ISSUER is a hard error instead of silently trusting the
    client-supplied Host header.
    """
    configured = getattr(settings, "OAUTH_ISSUER", "")
    if configured:
        return configured.rstrip("/")
    if settings.ENVIRONMENT not in _DEV_ENVIRONMENTS:
        logger.error("oauth_issuer_not_configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server OAuth issuer is not configured",
        )
    return str(request.base_url).rstrip("/")


def _resource_url(request: Request) -> str:
    """Protected resource URL — the MCP endpoint itself."""
    return f"{_issuer(request)}/mcp"


def _code_challenge_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _verify_pkce(verifier: str, challenge: str, method: str = "S256") -> bool:
    # OAuth 2.1 forbids `plain`: the challenge travels in the authorize URL, so
    # anyone who can read it derives the verifier. Only S256 is accepted.
    if method != "S256":
        return False
    try:
        return hmac.compare_digest(_code_challenge_s256(verifier), challenge)
    except (UnicodeEncodeError, TypeError):
        return False


# ── RS256 / JWKS (enterprise) ────────────────────────────────────────
# ponytail: generate once per process, expose via JWKS, KID rotation = new key + new KID

_RSA_KEYPAIR: tuple[Any, Any] | None = None
_KID = "stocklens-mcp-1"  # legacy kid for the ephemeral fallback key
_CONFIGURED_KID: str | None = None
_KEY_SOURCE: str | None = None  # fingerprint of the PEM the cached keypair came from
_RETIRED_JWKS: list[tuple[dict[str, Any], float]] = []  # (public JWK, rotated_at epoch)

_JWKS_RETENTION_SLACK_SECONDS = 300  # clock skew + client JWKS-refresh latency


def _jwks_retention_seconds() -> float:
    """How long a retired public key stays published after rotation.

    Must cover the access-token lifetime plus slack: a client that cached
    the JWKS just before the rotation still holds in-flight tokens signed
    with the retired key.
    """
    minutes = float(getattr(settings, "OAUTH_ACCESS_TOKEN_EXPIRE_MINUTES", 30))
    return minutes * 60.0 + _JWKS_RETENTION_SLACK_SECONDS


def _kid() -> str:
    """kid of the active signing key — fingerprint-derived when a PEM is configured."""
    return _CONFIGURED_KID or _KID


def _jwk_for(pub: Any, kid: str) -> dict[str, Any]:
    numbers = pub.public_numbers()
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _b64url_uint(numbers.n),
        "e": _b64url_uint(numbers.e),
    }


def _get_rsa_keypair():
    global _RSA_KEYPAIR, _CONFIGURED_KID, _KEY_SOURCE
    pem = settings.JWT_PRIVATE_KEY or ""
    fingerprint = hashlib.sha256(pem.encode()).hexdigest()[:16] if pem else None
    if _RSA_KEYPAIR is not None:
        if fingerprint == _KEY_SOURCE:
            return _RSA_KEYPAIR
        # In-process rotation: the configured key changed since the cached
        # keypair was loaded. Retire the old public JWK so JWKS-caching
        # clients can still verify in-flight tokens minted before the swap.
        _RETIRED_JWKS.append((_jwk_for(_RSA_KEYPAIR[1], _kid()), time.time()))
        _RSA_KEYPAIR = None
        _CONFIGURED_KID = None
    _KEY_SOURCE = fingerprint
    # Persistent key from Settings.JWT_PRIVATE_KEY when set; else ephemeral.
    if pem and _CRYPTO_AVAILABLE:
        try:
            priv = serialization.load_pem_private_key(pem.encode(), password=None)
            if not isinstance(priv, rsa.RSAPrivateKey):
                raise ValueError("JWT_PRIVATE_KEY must be an RSA private key")
            pub = priv.public_key()
            # kid = SHA-256 fingerprint of the public key (SPKI DER) — stable
            # across restarts and workers, so JWKS-caching clients never trust
            # a stale kid for the same key.
            der = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.PKCS1)
            _CONFIGURED_KID = hashlib.sha256(der).hexdigest()[:16]
            _RSA_KEYPAIR = (priv, pub)
            logger.info("jwt_private_key_loaded", kid=_CONFIGURED_KID)
            return _RSA_KEYPAIR
        except Exception as exc:
            logger.error("jwt_private_key_unusable_falling_back_to_ephemeral", error=str(exc))
    elif pem:
        logger.error("jwt_private_key_set_but_cryptography_unavailable")
    if not _CRYPTO_AVAILABLE:
        return None
    logger.warning(
        "jwt_private_key_not_configured_ephemeral_keys_in_use",
        impact="RS256 tokens invalid across restarts and multi-worker deployments",
        fix="set JWT_PRIVATE_KEY to a persistent RSA PEM (e.g. from Secrets Manager)",
    )
    # Ephemeral 2048-bit for dev/test
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key()
    _RSA_KEYPAIR = (priv, pub)
    return _RSA_KEYPAIR


def _b64url_uint(n: int) -> str:
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _public_jwk() -> dict[str, Any] | None:
    pair = _get_rsa_keypair()
    if pair is None:
        return None
    _, pub = pair
    return _jwk_for(pub, _kid())


def _jwks() -> dict[str, Any]:
    """Active JWK first, then retired keys still inside their retention window.

    Retired keys let JWKS-caching clients verify tokens minted before a
    rotation; each is dropped once its window elapses. History is in-memory
    only — a process restart republishes just the new key, so a restart-keyed
    rotation still asks clients to re-fetch (persistent history would need
    retired PEMs stored alongside JWT_PRIVATE_KEY).
    """
    current = _public_jwk()
    keys: list[dict[str, Any]] = []
    seen_kids: set[str] = set()
    if current is not None:
        keys.append(current)
        seen_kids.add(current["kid"])
    now = time.time()
    horizon = _jwks_retention_seconds()
    kept: list[tuple[dict[str, Any], float]] = []
    for jwk, rotated_at in _RETIRED_JWKS:
        if now - rotated_at < horizon and jwk["kid"] not in seen_kids:
            kept.append((jwk, rotated_at))
            seen_kids.add(jwk["kid"])
            keys.append(jwk)
    _RETIRED_JWKS[:] = kept
    return {"keys": keys}


def _private_pem() -> bytes | None:
    pair = _get_rsa_keypair()
    if pair is None:
        return None
    priv, _ = pair
    return priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _public_pem() -> bytes | None:
    pair = _get_rsa_keypair()
    if pair is None:
        return None
    _, pub = pair
    return pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _try_rs256_encode(payload: dict[str, Any]) -> str | None:
    """Try RS256 encode with kid, return None if not available."""
    pem = _private_pem()
    if pem is None:
        return None
    try:
        return pyjwt.encode(payload, pem, algorithm="RS256", headers={"kid": _kid()})
    except Exception:
        return None


def _mcp_create_access_token(user_id: str, scope: str = "mcp:tools"):
    """Create an MCP access token — RS256 if available, else HS256 fallback.

    ``scope`` is embedded so the MCP layer can authorise tool/resource access.
    The HS256 fallback encodes the same claim set directly (the REST helper has
    no scope) while staying decodable by ``decode_token``.
    """
    from datetime import datetime, timedelta, timezone

    jti = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=getattr(settings, "OAUTH_ACCESS_TOKEN_EXPIRE_MINUTES", 30))
    payload = {
        "sub": user_id,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "type": "access",
        "scope": scope,
    }
    tok = _try_rs256_encode(payload)
    if tok:
        return tok, jti, int(exp.timestamp())
    # Fallback HS256 via existing helper (ensures decode_token still works)
    tok = pyjwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return tok, jti, int(exp.timestamp())


def _mcp_create_refresh_token(user_id: str):
    """MCP refresh — keep HS256 for DB hash stability (RS256 not needed)."""
    return create_refresh_token(user_id)


def _decode_mcp_claims(token: str) -> dict[str, Any]:
    """Decode an MCP token (RS256 via the JWKS key, else HS256) to raw claims.

    Returning raw claims (not TokenPayload) lets callers read claims the
    TokenPayload schema does not model — notably the granted ``scope``.
    """
    # Try RS256 first if header says RS256
    try:
        hdr = pyjwt.get_unverified_header(token)
        if hdr.get("alg") == "RS256":
            pem = _public_pem()
            if pem:
                return pyjwt.decode(token, pem, algorithms=["RS256"])
    except Exception:
        pass
    # Fallback HS256 via existing helper semantics (same secret/alg/leeway)
    return pyjwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        leeway=10,
    )


def _decode_mcp_token(token: str) -> TokenPayload:
    """Decode MCP token supporting both RS256 (kid) and HS256."""
    return TokenPayload(**_decode_mcp_claims(token))


_AUTH_CODE_TTL = 600


async def _store_code(
    code: str,
    data: dict[str, Any],
    ttl: int = _AUTH_CODE_TTL,
) -> None:
    r = await get_redis()
    import json

    await r.set(f"oauth:code:{code}", json.dumps(data), ex=ttl)


async def _consume_code(code: str) -> dict[str, Any] | None:
    """Atomically claim (single-use) an auth code.

    GETDEL guarantees exactly one concurrent /oauth/token exchange wins the
    code, so two simultaneous exchanges can no longer both pass PKCE and both
    mint tokens. A replay of an already-consumed code finds the tombstone left
    at first use, is answered by revoking the tokens issued for that code
    (stolen-code response), and returns None so the caller raises 400.
    """
    r = await get_redis()
    import json

    key = f"oauth:code:{code}"
    try:
        raw = await r.getdel(key)
    except Exception:
        # Redis < 6.2 has no GETDEL — degrade to the non-atomic get+delete.
        logger.warning("oauth_code_getdel_unavailable")
        raw = await r.get(key)
        if raw is not None:
            await r.delete(key)
    if raw is None:
        # No live code: a replay if the first-use tombstone is still present.
        if await r.get(f"oauth:code:used:{code}") is not None:
            await _revoke_replayed_code(code)
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw)
    except Exception:
        return None
    # Tombstone (same TTL) so a later exchange can recognise a replay.
    await r.set(f"oauth:code:used:{code}", raw, ex=_AUTH_CODE_TTL)
    return data


async def _revoke_replayed_code(code: str) -> None:
    """Revoke every refresh token for the user of a replayed auth code.

    Mirrors the refresh-token reuse handler: a second exchange of an
    already-used code is treated as evidence the code was stolen.
    """
    r = await get_redis()
    import json

    raw = await r.get(f"oauth:code:used:{code}")
    if raw is None:
        return
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        user_id = json.loads(raw).get("user_id")
    except Exception:
        return
    if not user_id:
        return
    logger.warning("oauth_code_replay_detected", user_id=str(user_id)[:8])
    async with connection_ctx() as conn:
        await conn.execute(
            "UPDATE refresh_tokens SET revoked = true WHERE user_id = $1::uuid",
            user_id,
        )


# ── CIMD (OAuth Client ID Metadata Documents, draft-ietf-oauth-client-id-metadata-document) ──

_CIMD_TTL = 300  # seconds
_CIMD_MAX_CACHE_ENTRIES = 128
_CIMD_MAX_BYTES = 256 * 1024  # response size cap — hostile hosts must not OOM the worker
_CIMD_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class _RefuseRedirectsHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects on CIMD fetches.

    The SSRF guard validates only the initial host — following a redirect
    would let an approved public host 302 the fetch to link-local metadata
    services or internal endpoints. Refusing turns every 3xx into an
    HTTPError, which the fetch treats as a failed lookup.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_CIMD_OPENER = urllib.request.build_opener(_RefuseRedirectsHandler())


def _is_cimd_client_id(client_id: str) -> bool:
    """URL-formatted client_id is the CIMD registration signal."""
    return client_id.startswith("https://")


# POST /oauth/register hands out one static public client and the DCR stub
# persists nothing, so the first-party allowlist is hardcoded: the register
# defaults (loopback wildcard, claude.ai) plus the RFC 8252 §7.3 loopback
# redirect pattern with any port.
_FIRST_PARTY_HTTPS_HOSTS = frozenset({"claude.ai"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _is_first_party_redirect(uri: str) -> bool:
    """Allowlist for non-CIMD (first-party) client redirect URIs.

    OAuth 2.1 requires per-client redirect_uri matching — for the static
    public client every URI must be either a loopback redirect (any port,
    RFC 8252 §7.3) or a registered default host. Accepting anything else
    lets an attacker 302 the authorization code (bound to their own PKCE
    challenge) to a redirect they control → account takeover.
    """
    try:
        parts = urllib.parse.urlsplit(uri)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme == "http" and host in _LOOPBACK_HOSTS:
        return True
    return parts.scheme == "https" and host in _FIRST_PARTY_HTTPS_HOSTS


def _cimd_host_blocked(host: str) -> bool:
    """SSRF guard — refuse to fetch documents from non-public hosts.

    ponytail: resolves for a check, then fetches by name — a DNS-rebind TOCTOU
    remains. Harden with pinned-IP http.client connect if CIMD ever serves
    untrusted third-party clients.
    """
    if host in {"", "localhost"} or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)  # literal IP
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            return True  # unresolvable → treat as blocked
        addrs = {info[4][0] for info in infos}
    else:
        addrs = {host}

    for addr in addrs:
        ip = ipaddress.ip_address(addr)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_unspecified
            or ip.is_multicast
        ):
            return True
    return False


def _fetch_cimd_document(client_id: str) -> dict[str, Any] | None:
    """Fetch + validate a CIMD metadata document (sync; call via asyncio.to_thread)."""
    import json

    now = time.time()
    cached = _CIMD_CACHE.get(client_id)
    if cached and now - cached[0] < _CIMD_TTL:
        return cached[1]

    host = urllib.parse.urlsplit(client_id).hostname or ""
    if _cimd_host_blocked(host):
        logger.warning("cimd_ssrf_blocked", client_id=client_id)
        return None
    try:
        req = urllib.request.Request(
            client_id,
            headers={"Accept": "application/json", "User-Agent": "stocklens-mcp/0.1.0"},
        )
        with _CIMD_OPENER.open(req, timeout=5) as resp:
            # Stream-read with a hard cap so a hostile host streaming
            # gigabytes cannot pin the to_thread worker or exhaust memory.
            raw = resp.read(_CIMD_MAX_BYTES + 1)
        if len(raw) > _CIMD_MAX_BYTES:
            logger.warning("cimd_document_too_large", client_id=client_id)
            return None
        doc = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        logger.warning("cimd_fetch_failed", client_id=client_id, reason=str(exc))
        return None

    if not isinstance(doc, dict) or not isinstance(doc.get("redirect_uris"), list):
        return None
    # Bound the cache — TTL checks alone never evicted stale entries.
    while len(_CIMD_CACHE) >= _CIMD_MAX_CACHE_ENTRIES:
        _CIMD_CACHE.pop(next(iter(_CIMD_CACHE)))
    _CIMD_CACHE[client_id] = (now, doc)
    return doc


# ── Schemas ───────────────────────────────────────────────────────────────


class AuthorizeRequest(BaseModel):
    email: str
    password: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str = "S256"
    state: str | None = None
    scope: str | None = None


class TokenRequest(BaseModel):
    grant_type: str
    code: str | None = None
    redirect_uri: str | None = None
    client_id: str | None = None
    code_verifier: str | None = None
    refresh_token: str | None = None
    # client_credentials fallback (service-to-service)
    client_secret: str | None = None


# ── Well-known metadata ──────────────────────────────────────────────────


@router.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server_metadata(request: Request):
    """RFC 8414 Authorization Server Metadata."""
    iss = _issuer(request)
    return {
        "issuer": iss,
        "authorization_endpoint": f"{iss}/oauth/authorize",
        "token_endpoint": f"{iss}/oauth/token",
        "revocation_endpoint": f"{iss}/oauth/revoke",
        "registration_endpoint": f"{iss}/oauth/register",
        "jwks_uri": f"{iss}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["mcp:tools", "portfolio:read", "market:read"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "id_token_signing_alg_values_supported": ["RS256", "HS256"],
        "authorization_response_iss_parameter_supported": True,
    }


@router.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource_metadata(request: Request):
    """RFC 9728 Protected Resource Metadata — what MCP clients discover first."""
    iss = _issuer(request)
    return {
        "resource": _resource_url(request),
        "authorization_servers": [iss],
        "scopes_supported": ["mcp:tools", "portfolio:read", "market:read"],
        "bearer_methods_supported": ["header"],
    }


# Back-compat alias per older MCP drafts
@router.get("/.well-known/oauth-authorization-server/mcp")
async def oauth_as_mcp_alias(request: Request):
    return await oauth_authorization_server_metadata(request)


@router.get("/.well-known/jwks.json")
async def jwks_endpoint():
    """RFC 7517 JWKS — RS256 public keys for MCP token verification.

    The active signing key comes first; keys retired by an in-process
    rotation stay published for the access-token lifetime plus slack so
    JWKS-caching clients can still verify in-flight tokens.
    """
    return _jwks()


# ── Dynamic Client Registration (stub) ───────────────────────────────────


@router.post("/oauth/register")
async def oauth_register(request: Request):
    """DCR stub — MCP Inspector requires this for discovery.

    Returns a static public client (no secret) — correct for PKCE public clients.
    Add real client DB when multi-tenant matters.
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    redirect_uris = body.get("redirect_uris") or ["http://localhost:*", "https://claude.ai/*"]
    return {
        "client_id": "stocklens-mcp-public",
        "client_name": "StockLens MCP",
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "code_challenge_method": "S256",
    }


# ── Authorize ────────────────────────────────────────────────────────────


async def _authenticate_user(email: str, password: str) -> dict | None:
    email = email.lower().strip()
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, password_hash, is_active FROM users WHERE email = $1",
            email,
        )
    if row is None:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="Account is deactivated")
    return dict(row)


@router.get("/oauth/authorize")
async def oauth_authorize_get(
    request: Request,
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    state: str | None = None,
    scope: str | None = None,
):
    """Browser redirect flow: validates, then redirects with ?code=&state=.

    For programmatic clients use POST /oauth/authorize.
    """
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Only response_type=code supported")
    if not client_id or not redirect_uri or not code_challenge:
        raise HTTPException(
            status_code=400, detail="Missing client_id, redirect_uri, or code_challenge"
        )

    # No session — return login hint as JSON if not handling browser redirect templating
    # For CV: show we handle redirect correctly; implementors would render login page here.
    # ponytail: no HTML template bloat — instruct caller to POST credentials.
    return JSONResponse(
        {
            "detail": "POST credentials to /oauth/authorize with email/password + PKCE params",
            "hint": {
                "POST": "/oauth/authorize",
                "required": ["email", "password", "client_id", "redirect_uri", "code_challenge"],
                "received": {
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "code_challenge_method": code_challenge_method,
                    "state": state,
                    "scope": scope,
                },
            },
        },
        status_code=200,
    )


@router.post("/oauth/authorize")
@limiter.limit(settings.RATE_LIMIT_OAUTH_AUTHORIZE)
async def oauth_authorize_post(body: AuthorizeRequest, request: Request):
    """Programmatic authorize — validates user + PKCE, returns code.

    If redirect_uri is http loopback, returns JSON {code, state}.
    Otherwise 302 to redirect_uri?code=&state= (spec-compliant).

    Rate limited: this endpoint verifies a password, so unthrottled it is a
    credential-stuffing / brute-force oracle.
    """
    if not body.code_challenge:
        raise HTTPException(status_code=400, detail="code_challenge required")
    if body.code_challenge_method != "S256":
        # OAuth 2.1: only S256 PKCE — reject plain up front rather than at exchange.
        raise HTTPException(status_code=400, detail="code_challenge_method must be S256")

    # CIMD: URL-formatted client_id = fetch metadata document, enforce redirect_uri
    client_name: str | None = None
    if _is_cimd_client_id(body.client_id):
        doc = await asyncio.to_thread(_fetch_cimd_document, body.client_id)
        if doc is None:
            raise HTTPException(
                status_code=400, detail="Invalid or unreachable client_id metadata document"
            )
        redirect_uris = doc.get("redirect_uris") or []
        if body.redirect_uri not in redirect_uris:
            raise HTTPException(
                status_code=400, detail="redirect_uri not listed in client_id metadata document"
            )
        client_name = doc.get("client_name") or "external-client"
        logger.info("cimd_client_resolved", client_id=body.client_id[:64], client_name=client_name)
    elif not _is_first_party_redirect(body.redirect_uri):
        # First-party/static client (and any non-https client_id): the auth
        # code must only reach a registered or loopback redirect — honouring
        # a client-chosen redirect_uri is a code-injection account takeover.
        raise HTTPException(status_code=400, detail="redirect_uri not allowed for this client")

    user = await _authenticate_user(body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    code = secrets.token_urlsafe(32)
    await _store_code(
        code,
        {
            "user_id": str(user["id"]),
            "client_id": body.client_id,
            "client_name": client_name or "StockLens MCP",
            "redirect_uri": body.redirect_uri,
            "code_challenge": body.code_challenge,
            "code_challenge_method": body.code_challenge_method,
            "scope": body.scope or "mcp:tools",
            "created_at": int(time.time()),
        },
    )
    logger.info("oauth_code_issued", user_id=str(user["id"])[:8], client_id=body.client_id[:64])

    # Spec: redirect with code if redirect_uri is non-loopback; for inspector loopback return JSON.
    # RFC 9207: iss param on authorization responses (strict string comparison, no normalization).
    iss_param = urllib.parse.quote(_issuer(request), safe="")
    if body.redirect_uri.startswith("http://localhost") or body.redirect_uri.startswith(
        "http://127.0.0.1"
    ):
        return {"code": code, "state": body.state, "iss": _issuer(request)}

    # 302 redirect for browser clients
    sep = "&" if "?" in body.redirect_uri else "?"
    loc = f"{body.redirect_uri}{sep}code={code}&iss={iss_param}"
    if body.state:
        loc += f"&state={body.state}"
    return RedirectResponse(url=loc, status_code=302)


# ── Token ────────────────────────────────────────────────────────────────


@router.post("/oauth/token")
async def oauth_token(request: Request):
    """Token endpoint — authorization_code (with PKCE) and refresh_token.

    Accepts application/x-www-form-urlencoded (spec) and JSON (inspector convenience).
    """
    # Parse both form and JSON
    data: dict[str, Any] = {}
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            data = await request.json()
        except Exception:
            data = {}
    else:
        try:
            form = await request.form()
            data = dict(form)
        except Exception:
            try:
                data = await request.json()
            except Exception:
                data = {}

    grant_type = data.get("grant_type")

    # ── Authorization Code ─────────────────────────────────────────────
    if grant_type == "authorization_code":
        code = data.get("code")
        verifier = data.get("code_verifier")
        redirect_uri = data.get("redirect_uri")
        client_id = data.get("client_id")

        if not code or not verifier:
            raise HTTPException(status_code=400, detail="code and code_verifier required")

        stored = await _consume_code(code)
        if stored is None:
            raise HTTPException(status_code=400, detail="Invalid or expired authorization code")

        # OAuth 2.1: redirect_uri is mandatory at exchange and must match the
        # authorize request exactly; client_id must match the authorized one.
        if not redirect_uri:
            raise HTTPException(status_code=400, detail="redirect_uri required")
        if stored.get("redirect_uri") != redirect_uri:
            raise HTTPException(status_code=400, detail="redirect_uri mismatch")

        if client_id and stored.get("client_id") != client_id:
            raise HTTPException(status_code=400, detail="client_id mismatch")

        # PKCE verify
        challenge = stored.get("code_challenge", "")
        method = stored.get("code_challenge_method", "S256")
        if not _verify_pkce(verifier, challenge, method):
            raise HTTPException(status_code=400, detail="PKCE verification failed")

        user_id = stored["user_id"]
        scope = stored.get("scope", "mcp:tools")

        # Issue tokens — RS256 (JWKS) with HS256 fallback
        access_token, _, exp_int = _mcp_create_access_token(user_id, scope)
        refresh_token, rjti = _mcp_create_refresh_token(user_id)
        rdecoded = decode_token(refresh_token)

        # Persist refresh hash (rotation + revocation)
        token_hash = hash_token(rjti, user_id)
        async with connection_ctx() as conn:
            await conn.execute(
                "INSERT INTO refresh_tokens "
                "(user_id, token_hash, expires_at) "
                "VALUES ($1::uuid, $2, to_timestamp($3))",
                user_id,
                token_hash,
                rdecoded.exp,
            )

        logger.info(
            "oauth_token_issued",
            user_id=user_id[:8],
            scope=scope,
            alg="RS256" if _public_pem() else "HS256",
        )
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": max(0, exp_int - int(time.time())),
            "refresh_token": refresh_token,
            "scope": scope,
        }

    # ── Refresh Token ──────────────────────────────────────────────────
    if grant_type == "refresh_token":
        rtoken = data.get("refresh_token")
        if not rtoken:
            raise HTTPException(status_code=400, detail="refresh_token required")
        try:
            payload = _decode_mcp_token(rtoken)
        except pyjwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Refresh token expired")
        except pyjwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        if payload.type != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        if await is_token_blacklisted(payload.jti):
            raise HTTPException(status_code=401, detail="Refresh token revoked")

        token_hash = hash_token(payload.jti, payload.sub)
        # Atomic single-statement rotation claim: the conditional UPDATE is the
        # concurrency gate. Two concurrent refreshes of the same token can no
        # longer both pass a check-then-act window and double-mint — the loser
        # sees rowcount 0 and lands in the stolen-token path below.
        async with connection_ctx() as conn:
            claimed = await conn.fetchval(
                "UPDATE refresh_tokens SET revoked = true "
                "WHERE token_hash = $1 AND revoked = false "
                "RETURNING true",
                token_hash,
            )
        if claimed is None:
            # Distinguish unknown token (plain 401) from already-revoked
            # replay (stolen-token revoke-all) — read-only after the atomic
            # decision, so no race window remains.
            async with connection_ctx() as conn:
                row = await conn.fetchrow(
                    "SELECT revoked FROM refresh_tokens WHERE token_hash = $1", token_hash
                )
            if row is None:
                raise HTTPException(status_code=401, detail="Refresh token not found")
            # Stolen-token: revoke all
            async with connection_ctx() as conn:
                await conn.execute(
                    "UPDATE refresh_tokens SET revoked = true WHERE user_id = $1::uuid",
                    payload.sub,
                )
            raise HTTPException(status_code=401, detail="Refresh token revoked — re-login required")

        # Rotate
        from src.cache.redis import blacklist_token

        await blacklist_token(payload.jti, 86400)

        new_access, _, new_exp = _mcp_create_access_token(payload.sub)
        new_refresh, new_rjti = _mcp_create_refresh_token(payload.sub)
        rdecoded = decode_token(new_refresh)
        new_hash = hash_token(new_rjti, payload.sub)
        async with connection_ctx() as conn:
            await conn.execute(
                "INSERT INTO refresh_tokens "
                "(user_id, token_hash, expires_at) "
                "VALUES ($1::uuid, $2, to_timestamp($3))",
                payload.sub,
                new_hash,
                rdecoded.exp,
            )

        return {
            "access_token": new_access,
            "token_type": "Bearer",
            "expires_in": max(0, new_exp - int(time.time())),
            "refresh_token": new_refresh,
            "scope": "mcp:tools",
        }

    raise HTTPException(status_code=400, detail=f"Unsupported grant_type: {grant_type}")


@router.post("/oauth/revoke")
async def oauth_revoke(request: Request):
    """RFC 7009 revocation — revoke access or refresh token."""
    data: dict[str, Any] = {}
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            data = await request.json()
        except Exception:
            data = {}
    else:
        try:
            form = await request.form()
            data = dict(form)
        except Exception:
            data = {}
    token = data.get("token")
    hint = data.get("token_type_hint")
    if not token:
        return {"revoked": False}

    try:
        payload = _decode_mcp_token(token)
    except Exception:
        return {"revoked": False}

    if payload.type == "refresh" or hint == "refresh_token":
        h = hash_token(payload.jti, payload.sub)
        async with connection_ctx() as conn:
            await conn.execute("UPDATE refresh_tokens SET revoked = true WHERE token_hash = $1", h)
        from src.cache.redis import blacklist_token

        await blacklist_token(payload.jti, 86400)
    else:
        # Access token — blacklist JTI for remaining TTL
        from src.cache.redis import blacklist_token

        remaining = max(0, payload.exp - int(time.time()))
        if remaining > 0:
            await blacklist_token(payload.jti, remaining)

    return {"revoked": True}


# ── Scope → tool/resource authorization ────────────────────────────────
# `mcp:tools` is the umbrella scope granting every MCP tool; the finer scopes
# limit a client to portfolio or market data. A REST access token carries no
# OAuth scope and therefore no longer reaches MCP tools.

MCP_TOOLS_SCOPE = "mcp:tools"

_PORTFOLIO_TOOLS = frozenset(
    {
        "get_portfolio_summary",
        "get_portfolio_holdings",
        "get_sector_exposure",
        "get_portfolio_performance",
        "get_portfolio_diversification_score",
        "get_spending_analysis",
        "get_recent_transactions",
        "get_cash_flow_summary",
    }
)
_MARKET_TOOLS = frozenset(
    {
        "compare_to_benchmark",
        "compare_tickers_side_by_side",
        "get_market_ohlcv",
        "get_market_quote",
        "get_ticker_info",
        "get_market_news",
        "get_lstm_forecast",
        "get_dividend_insights",
    }
)
_TOOL_SCOPE: dict[str, str] = {
    **{name: "portfolio:read" for name in _PORTFOLIO_TOOLS},
    **{name: "market:read" for name in _MARKET_TOOLS},
}
_RESOURCE_SCOPE: dict[str, str] = {
    "portfolio://holdings": "portfolio:read",
    "portfolio://summary": "portfolio:read",
}
_PROMPT_SCOPE: dict[str, str] = {"analyze-portfolio": "portfolio:read"}


def granted_scopes(scope: str | None) -> frozenset[str]:
    """Split a space-delimited OAuth scope string into a set."""
    return frozenset((scope or "").split())


def tool_scope(tool_name: str) -> str:
    """Scope that authorises *tool_name* beyond the mcp:tools umbrella."""
    return _TOOL_SCOPE.get(tool_name, MCP_TOOLS_SCOPE)


def resource_scope(uri: str) -> str | None:
    """Scope required for an MCP resource URI, or None if unknown."""
    return _RESOURCE_SCOPE.get(uri)


def prompt_scope(name: str) -> str | None:
    """Scope required for an MCP prompt, or None if unknown."""
    return _PROMPT_SCOPE.get(name)


def scope_grants(granted: frozenset[str] | set[str], required: str) -> bool:
    """True when *granted* covers *required* (mcp:tools grants everything)."""
    return MCP_TOOLS_SCOPE in granted or required in granted


# ── Verifier for MCP handlers ──────────────────────────────────────────


@dataclass(frozen=True)
class McpPrincipal:
    """Verified MCP caller — user id plus the token's granted OAuth scopes."""

    sub: str
    scopes: frozenset[str]


async def verify_mcp_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_mcp_security),
) -> McpPrincipal:
    """FastAPI dependency — validates Bearer token for MCP endpoints.

    On failure raises 401 with WWW-Authenticate: Bearer + resource_metadata
    per MCP Authorization spec (2025-06-18).
    """
    iss = _issuer(request)
    resource_meta = f"{iss}/.well-known/oauth-protected-resource"

    def _unauth(detail: str, scope: str = MCP_TOOLS_SCOPE) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={
                "WWW-Authenticate": f'Bearer realm="stocklens", error="invalid_token", '
                f'resource_metadata="{resource_meta}", scope="{scope}"'
            },
        )

    if credentials is None:
        raise _unauth("Authentication required")

    token = credentials.credentials
    try:
        claims = _decode_mcp_claims(token)
        payload = TokenPayload(**claims)
    except pyjwt.ExpiredSignatureError:
        raise _unauth("Token has expired")
    except pyjwt.InvalidTokenError:
        raise _unauth("Invalid token")

    if payload.type != "access":
        raise _unauth("Invalid token type — expected access token")

    if await is_token_blacklisted(payload.jti):
        raise _unauth("Token has been revoked")

    try:
        uuid.UUID(payload.sub)
    except (ValueError, TypeError, AttributeError):
        # A non-UUID sub would surface as a 500 from the ::uuid cast below.
        raise _unauth("Invalid token")

    # Ensure user still exists/active
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, is_active FROM users WHERE id = $1::uuid", payload.sub
        )
    if row is None:
        raise _unauth("User not found")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    return McpPrincipal(sub=payload.sub, scopes=granted_scopes(claims.get("scope")))
