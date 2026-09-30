# ADR 0034: Cookie JWT, Redis sessions, and versioned RBAC

- Status: Accepted
- Date: 2026-09-26

## Context

The browser previously persisted access credentials in JavaScript storage, while authorization depended primarily on static role checks. This made credential exposure harder to contain and permission changes difficult to apply immediately.

## Decision

Use short-lived JWTs in HttpOnly cookies. A JWT contains only a cryptographically random `sid`, token type, random `jti`, issuer, audience, issue time, and expiry; it does not carry identity or authorization claims. Generate each SID with `secrets.token_urlsafe(32)`. Redis stores the authoritative SID session (`user_id`, timestamps, and the SHA-256 hash of the independently random rotating refresh secret); the SID stays stable through refresh rotation. Login and refresh require a trusted Origin and HMAC-backed double-submit CSRF token. WebSocket handshakes authenticate with the same cookies.

MySQL remains the source of truth for user status, current college, role-permission relationships, and a singleton authorization version. Every authenticated request rechecks the live user status/college and reads the version. Redis caches role/permission snapshots by `(sid, authz_version)`; permission/role assignment changes increment the version, and Redis cache failures fall back to MySQL. If Redis cannot validate the authoritative login session, authentication fails closed. The existing `STUDENT`, `LAB_ADMIN`, and `SYS_ADMIN` role codes remain; built-in `SYS_ADMIN` permissions are immutable.

Public registration creates an active ordinary user in one enabled college and immediately establishes a session. School SSO remains out of scope. The `/api/v2` migration is a one-time cutover: migration `0029` revokes old database refresh sessions and users must authenticate again. No Bearer-token or dual-auth compatibility path is retained.

## Consequences

- Access tokens can be revoked immediately by deleting the Redis SID session, and refresh-token replay revokes that session.
- Redis is required for authentication availability, but Redis outage does not change reservation correctness because MySQL constraints remain authoritative.
- Browser writes require a configured exact public Origin; production must use HTTPS, `LAB_COOKIE_SECURE=true`, and the matching `APP_PUBLIC_ORIGIN`.
- Permission updates apply on the next request after the MySQL authorization version commits; the cache key prevents stale snapshots from being reused.
- All existing sessions are revoked at cutover, so users must log in again after applying the migration.
