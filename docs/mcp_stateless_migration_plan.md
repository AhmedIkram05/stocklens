# Implementation Plan: MCP 2026-07-28 Stateless Migration + Auth Hardening

> **Status: IMPLEMENTED (2026-08-29).** All three phases shipped — dual-version core
> (server.py), auth hardening (auth.py), docs (docs/mcp.md + README) — with **93 MCP tests
> green** in the full suite run. See docs/mcp.md → "Protocol Support — Dual-Version" for
> the shipped behaviour.

## Overview

Update the StockLens MCP server from the 2025-06-18 initialize-based protocol to the
**2026-07-28 stateless core**, while keeping legacy clients working via a **dual-version
`server/discover`** endpoint, and fold in the spec's **auth hardening** items (issuer
validation, CIMD client registration, scope-bearing 401s).

The 2026-07-28 spec removes the `initialize` handshake entirely: every request carries
`params._meta` (`protocolVersion`, `clientInfo`, `clientCapabilities`), the server
advertises supported versions via the required `server/discover` RPC, and cross-call state
moves from protocol sessions to explicit handles passed as tool arguments. There is **no
backwards-compatibility fallback** — old clients get explicit errors (code −32022 for
version mismatch). Dual-version support is therefore the only way to keep the existing
Claude Desktop / Inspector demo working while advertising the new spec.

On the auth side, DCR (RFC 7591) is now deprecated in favour of **CIMD** (OAuth Client ID
Metadata Documents), authorization responses should carry `iss` per RFC 9207, and 401
challenges should guide clients toward least-privilege scope selection. StockLens already
has OAuth 2.1 PKCE + RS256/JWKS, so this is a natural extension.

## Constraints / Decisions

- **Dual-version, no fallback.** The server advertises `["2026-07-28", "2025-06-18"]` in
  `server/discover`. The `2025-06-18` path (`initialize` → `notifications/initialized`) is
  preserved unchanged. Requests without `_meta` default to the legacy path; requests with
  an unsupported `protocolVersion` get error **−32022** with `data: {supported, requested}`.
  **This is the spec-designed, industry-standard transition pattern**, not a workaround:
  (1) the spec's own unsupported-version example advertises a multi-version list
  (`"supported": ["2026-07-28", "2025-11-25"]`); (2) the protocol-versioning section
  instructs clients to "select a mutually supported version from this list to retry";
  (3) the stdio Backward Compatibility section explicitly describes dual-mode clients that
  probe `server/discover` and "fall back to the initialize handshake" when the server
  fails to answer it. Serving multiple versions is the protocol's designed migration path
  until the installed client population moves to 2026-07-28.
- **`initialize` is rejected on 2026-07-28.** Under the new protocol version the method
  doesn't exist (method-not-found), which is what a conforming 2026-07-28 client expects.
  Legacy clients (pre-discover, no `_meta`) keep working as today.
- **Keep `GET /mcp` SSE endpoint-event.** The new spec removes the GET stream and tells
  servers to answer legacy GET traffic with 405. We deliberately keep GET because
  dual-version means legacy clients must keep working — documented as a dual-version
  necessity, not a spec violation.
- **Auth hardening is in scope:** issuer param + metadata flag, CIMD, 401 `scope=`
  guidance. DCR's AS-binding requirement is already satisfied structurally (the AS is
  server-authoritative) — no code change, documented only.
- **SDK stays as-is.** `create_mcp_app()` keeps serving the legacy path via the installed
  `mcp` SDK (`>=1.12,<2`) with a comment noting it's the SDK-native legacy path until an
  SDK release implements 2026-07-28. No SDK upgrade in this migration.
- **Out of scope:** Enterprise-Managed Authorization (separate extension; add later if a
  client needs it), LAAD migration (separate work item), mTLS / per-scope enforcement
  (already listed as the next rung in docs/mcp.md's security checklist).

## Requirements

- `server/discover` returns `resultType: "complete"`, `supportedVersions`, `capabilities`
  ({tools, resources}), `_meta.serverInfo` (name, version), `instructions`, `ttlMs`
  (3600000), `cacheScope: "public"`.
- Per-request `_meta` on the 2026-07-28 path gates version; unsupported version → −32022.
- All tool/resource/prompt functions work identically under both versions (no protocol
  state was ever used — already stateless in practice).
- Issuer (`iss`) appears in authorization responses (including error responses) and
  `oauth_authorization_server_metadata` advertises
  `authorization_response_iss_parameter_supported: true`.
- `client_id` given as a URL is resolved via CIMD: fetch + validate the client's metadata
  document, enforce `redirect_uri` membership, use `client_name` for any consent display;
  SSRF-guard the fetch (private/loopback ranges blocked).
- 401 `WWW-Authenticate` challenges extended with `scope="..."` so clients can pick
  least-privilege scopes.
- All existing 1,250 lines of MCP tests stay green; new tests cover the above.
- Docs updated: docs/mcp.md (spec section, endpoint map, security checklist), CV bullet.

## Architecture Changes

- `backend/src/mcp/server.py` (`mcp_post`, ~line 92):
  - Parse `params._meta["io.modelcontextprotocol/protocolVersion"]` per message; absent →
    `"2025-06-18"` (legacy default), present-but-unsupported → −32022 via `_error` with
    `data: {supported: [...], requested: '...'}`.
  - New message handler for `server/discover` returning the discover result above.
  - On `"2026-07-28"`: reject `initialize` / `notifications/initialized` (method not
    found); everything else (tools/_, resources/_, prompts/*, ping) proceeds unchanged.
  - Responses on the new path include server identification `_meta` (spec allows
    identification "in each request or result" — **open item:** confirm the exact
    result-side field placement from the spec before implementing).
- `backend/src/mcp/auth.py`:
  - `oauth_authorization_server_metadata` (RFC 8414): add
    `authorization_response_iss_parameter_supported: true`.
  - `oauth_authorize_get` / `oauth_authorize_post`: append `iss={ISSUER}` (and the flag)
    to authorization/error redirects per RFC 9207.
  - `oauth_register` + `oauth_token`/authorize path: if `client_id` is a URL (starts
    `https://`), treat as CIMD — fetch the document, validate structure, enforce
    `redirect_uri` ∈ `redirect_uris`, prefer `client_name`. SSRF guard: resolve host via
    stdlib `ipaddress`, reject private/loopback/link-local/unspecified; fetch with a short
    timeout; cache validated documents in-memory with TTL (e.g. 300s) rather than per
    request.
  - `_unauth` (auth.py ~line 693): `WWW-Authenticate: Bearer resource_metadata="...",
scope="portfolio:read"` (resource_metadata already present; add scope guidance).
- No schema changes. No new dependencies (stdlib `urllib`, `ipaddress`, `functools`
  cover CIMD fetch + cache).

## Implementation Steps

### Phase 1 — Protocol core: discover + dual-version gate (server.py)

1. Add module-level `SUPPORTED_VERSIONS = ["2026-07-28", "2025-06-18"]` and helpers:
   `_request_version(meta: dict) -> str` (absent → legacy default; unsupported → raise
   handled as −32022) and `_discover_result() -> dict`.
2. In `mcp_post`'s per-message loop: resolve version first; branch on
   `"2026-07-28"` for discover/initialize rejection; keep the existing handlers as the
   shared implementation for tools/resources/prompts/ping.
3. Keep `GET /mcp` SSE endpoint-event and `Accept: text/event-stream` response handling
   untouched (dual-version legacy support).
4. `create_mcp_app()` (line ~311): add a `ponytail:` comment noting the SDK-native
   streamable_http_app is the legacy (2025-06-18) path until an SDK release implements
   2026-07-28; no functional change.
5. Tests in `backend/tests/test_mcp_server.py`:
   - `server/discover` returns supportedVersions/capabilities/serverInfo/ttlMs/cacheScope.
   - request with `protocolVersion: "2020-01-01"` → −32022 with data.supported/requested.
   - `tools/list` + `tools/call` on "2026-07-28" (with `_meta`) succeed.
   - `initialize` on "2026-07-28" → method-not-found error.
   - legacy `initialize` (no `_meta`) still returns protocolVersion "2025-06-18".

### Phase 2 — Auth hardening (auth.py)

1. `iss` on `oauth_authorize_get`/`oauth_authorize_post` redirects (success + error) and
   `authorization_response_iss_parameter_supported: true` in the AS metadata.
2. CIMD: URL-formatted `client_id` resolution in `oauth_authorize_post` +
   `oauth_register`; SSRF guard + in-memory TTL cache; `redirect_uri` enforcement.
   DCR stub stays for the Inspector (DCR is deprecated but backwards-compat-only).
3. `_unauth`: append `scope` to the 401 `WWW-Authenticate` header.
4. Tests in `backend/tests/test_mcp_auth.py`:
   - metadata advertises `authorization_response_iss_parameter_supported: true`;
     authorize response contains `iss`.
   - CIMD: mocked fetch — valid doc accepted, `redirect_uri` mismatch rejected,
     private-range client_id URL rejected (SSRF), invalid doc rejected.
   - 401 challenge includes `scope="..."`.

### Phase 3 — Docs, evidence, full verification

1. docs/mcp.md: new "Protocol support" section (dual-version matrix, discover, −32022,
   deliberate GET-retention note), auth section updates (CIMD, iss, scope-aware 401),
   security checklist: tick CIMD/iss/scope items (mTLS per-scope stays unticked).
2. CV bullet refresh: add "2026-07-28 stateless core (dual-version discover), CIMD
   registration, RFC 9207 issuer validation".
3. Demo re-verification: `docker compose run --rm pytest` (full suite green) + Inspector
   run (`npx @modelcontextprotocol/inspector`); note the Inspector may still exercise the
   legacy path — that's expected and covered by dual-version.
4. README MCP section: add a "Modern MCP (2026-07-28)" note — stateless discover +
   dual-version + CIMD; keep the existing OAuth 2.1 PKCE description as-is (verify README
   mentions MCP and update the relevant section).

## Open Items (resolved during implementation)

- **`_meta` on responses: RESOLVED.** The `server/discover` result **requires**
  `_meta.io.modelcontextprotocol/serverInfo` (name, version) — that is the server's
  identification "in each request or result". Other method results do not repeat it;
  server identity is established once via discover.
- **CIMD document fields: RESOLVED.** `redirect_uris` (list) + `client_name` are the
  practiced minimum of draft-ietf-oauth-client-id-metadata-document-00; implementation
  validates structure + `redirect_uris` membership and logs `client_name`.
- **405 semantics: n/a.** We keep GET /mcp deliberately (dual-version, documented in
  Constraints / Decisions); no other legacy verbs exist on this endpoint.

## Rollback

- Revert = drop the version branch and CIMD block; discover is additive, `iss` metadata
  flag is additive, scope on 401 is additive. Legacy path (initialize, GET SSE, DCR stub,
  SDK app) is untouched by every phase.
