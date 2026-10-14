"""Black-box OWASP WSTG checks for the LabFlow authentication API.

This runner is deliberately independent from backend/tests and sends HTTP
requests through OWASP ZAP. It creates one uniquely named account through the
public registration route, temporarily disables only that account for the
enumeration check, and removes its own database and Redis artifacts on exit.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import statistics
import sys
import time
from datetime import UTC, datetime
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import jwt
from redis.asyncio import Redis
from sqlalchemy import delete, select, update

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.settings import Settings
from app.infrastructure.db.models import User, user_roles
from app.infrastructure.db.session import build_engine, build_session_factory

API_PREFIX = "/api/v2"
AUTH = f"{API_PREFIX}/auth"
ACCESS_COOKIE = "lab_access"
REFRESH_COOKIE = "lab_refresh"
CSRF_COOKIE = "lab_csrf"
CATEGORIES = {
    "WSTG-IDNT-04": "账号枚举",
    "WSTG-ATHN-03": "暴力尝试与限流",
    "WSTG-SESS-05": "登录 CSRF",
    "WSTG-SESS-02 / WSTG-ATHN-01": "Cookie 属性与传输安全",
    "WSTG-SESS-10": "JWT 校验",
    "WSTG-SESS-06 / WSTG-SESS-07 / WSTG-SESS-11": "会话生命周期",
    "WSTG-IDNT-02 / WSTG-ATHN-07": "注册与密码处理",
    "WSTG-ATHN-04 / WSTG-INPV-01 / WSTG-INPV-05": "认证绕过与输入探针",
}


def cookie_values(response: httpx.Response) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    values: dict[str, str] = {}
    attrs: dict[str, dict[str, str]] = {}
    for raw in response.headers.get_list("set-cookie"):
        parsed = SimpleCookie()
        parsed.load(raw)
        for name, morsel in parsed.items():
            values[name] = morsel.value
            attrs[name] = {
                "path": morsel["path"],
                "domain": morsel["domain"],
                "secure": morsel["secure"],
                "httponly": morsel["httponly"],
                "samesite": morsel["samesite"],
                "max-age": morsel["max-age"],
                "expires": morsel["expires"],
            }
    return values, attrs


def cookie_header(values: dict[str, str]) -> str:
    return "; ".join(f"{key}={value}" for key, value in values.items())


def response_error(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        body = response.json()
    except ValueError:
        return None, None
    if not isinstance(body, dict):
        return None, None
    code = body.get("code")
    message = body.get("message")
    return (str(code) if code is not None else None, str(message) if message is not None else None)


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class WstgRun:
    def __init__(self) -> None:
        self.base = os.environ["QA_OWASP_BASE_URL"].rstrip("/")
        self.rate_base = os.environ["QA_OWASP_RATE_BASE_URL"].rstrip("/")
        self.rate_direct_base = os.environ["QA_OWASP_RATE_DIRECT_URL"].rstrip("/")
        self.origin = os.environ["QA_OWASP_ORIGIN"].rstrip("/")
        self.rate_origin = os.environ["QA_OWASP_RATE_ORIGIN"].rstrip("/")
        self.proxy = os.environ["QA_OWASP_ZAP_PROXY"]
        self.zap_api = os.environ["QA_OWASP_ZAP_API"].rstrip("/")
        self.zap_key = os.environ["QA_OWASP_ZAP_API_KEY"]
        self.jwt_secret = os.environ["QA_OWASP_JWT_SECRET"]
        self.rate_redis_url = os.environ["QA_OWASP_RATE_REDIS_URL"]
        self.settings = Settings()
        self.engine = build_engine(self.settings)
        self.session_factory = build_session_factory(self.engine)
        self.redis_main: Redis = Redis.from_url(self.settings.redis_url, decode_responses=True)
        self.redis_rate: Redis = Redis.from_url(self.rate_redis_url, decode_responses=True)
        self.run_id = datetime.now(UTC).strftime("%Y%m%d") + "-" + secrets.token_hex(4)
        self.username = f"owasp-{self.run_id}"
        self.weak_username = f"{self.username}-weak"
        self.password = "Owasp-" + secrets.token_urlsafe(16) + "-A9!"
        self.user_id: int | None = None
        self.college_id: int | None = None
        self.session_ids: set[str] = set()
        self.checks: list[dict[str, Any]] = []
        self.started_at = datetime.now(UTC)
        self.report_dir = Path(os.getenv("QA_OWASP_RESULTS", str(ROOT / "qa_owasp" / "results")))
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def check(self, category: str, name: str, passed: bool | None, evidence: str) -> None:
        self.checks.append(
            {
                "category": category,
                "name": name,
                "status": "PASS" if passed is True else "FAIL" if passed is False else "UNVERIFIED",
                "evidence": evidence[:300],
            }
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            proxy=self.proxy,
            timeout=httpx.Timeout(20.0, connect=8.0),
            follow_redirects=False,
            trust_env=False,
        )

    async def csrf(
        self, client: httpx.AsyncClient, base: str, origin: str
    ) -> tuple[str, dict[str, str]]:
        response = await client.get(f"{base}{AUTH}/csrf")
        token = str(response.json()["data"]["csrf_token"])
        values, _ = cookie_values(response)
        values[CSRF_COOKIE] = token
        return token, values

    @staticmethod
    def mutation_headers(token: str, cookies: dict[str, str], origin: str) -> dict[str, str]:
        return {
            "Origin": origin,
            "X-CSRF-Token": token,
            "Cookie": cookie_header(cookies),
        }

    def remember_session(self, cookies: dict[str, str]) -> None:
        access = cookies.get(ACCESS_COOKIE)
        refresh = cookies.get(REFRESH_COOKIE)
        if refresh and "." in refresh:
            self.session_ids.add(refresh.split(".", 1)[0])
        if access:
            try:
                claims = jwt.decode(
                    access,
                    options={"verify_signature": False, "verify_exp": False},
                    algorithms=["HS256"],
                )
                if isinstance(claims.get("sid"), str):
                    self.session_ids.add(claims["sid"])
            except jwt.PyJWTError:
                pass

    async def login(
        self,
        client: httpx.AsyncClient,
        base: str,
        origin: str,
        username: str,
        password: str,
    ) -> tuple[httpx.Response, dict[str, str]]:
        token, csrf_cookies = await self.csrf(client, base, origin)
        response = await client.post(
            f"{base}{AUTH}/login",
            json={"username": username, "password": password},
            headers=self.mutation_headers(token, csrf_cookies, origin),
        )
        values, _ = cookie_values(response)
        self.remember_session(values)
        return response, values

    async def user_record(self) -> tuple[int, str] | None:
        async with self.session_factory() as session:
            row = await session.scalar(select(User).where(User.username == self.username))
            if row is None:
                return None
            return int(row.id), str(row.password_hash)

    async def set_user_status(self, status: int) -> None:
        if self.user_id is None:
            return
        async with self.session_factory() as session:
            await session.execute(update(User).where(User.id == self.user_id).values(status=status))
            await session.commit()

    async def registration_suite(self, client: httpx.AsyncClient) -> None:
        category = "WSTG-IDNT-02 / WSTG-ATHN-07"
        colleges = await client.get(f"{self.base}{AUTH}/colleges")
        rows = colleges.json().get("data", [])
        if not rows:
            self.check(
                category, "存在可注册的学院", False, f"HTTP {colleges.status_code}; college_count=0"
            )
            return
        self.college_id = int(rows[0]["id"])
        token, cookies = await self.csrf(client, self.base, self.origin)

        base_payload = {
            "username": self.username,
            "password": self.password,
            "real_name": "OWASP WSTG probe",
            "college_id": self.college_id,
            "role_codes": ["SYS_ADMIN"],
            "roles": ["SYS_ADMIN"],
        }
        for label, candidate in (
            ("7-character password rejected", "A1!xYz9"),
            ("129-character password rejected", "A" * 129),
            ("empty password rejected", ""),
        ):
            payload = {
                **base_payload,
                "username": f"{self.username}-{secrets.token_hex(2)}",
                "password": candidate,
            }
            response = await client.post(
                f"{self.base}{AUTH}/register",
                json=payload,
                headers=self.mutation_headers(token, cookies, self.origin),
            )
            self.check(category, label, response.status_code == 422, f"HTTP {response.status_code}")

        response = await client.post(
            f"{self.base}{AUTH}/register",
            json=base_payload,
            headers=self.mutation_headers(token, cookies, self.origin),
        )
        self.check(
            category,
            "registration succeeds with baseline payload",
            response.status_code == 201,
            f"HTTP {response.status_code}",
        )
        if response.status_code != 201:
            return
        issued, _ = cookie_values(response)
        self.remember_session(issued)
        row = await self.user_record()
        if row is None:
            self.check(
                category, "password is persisted as a hash", False, "registered user row missing"
            )
        else:
            self.user_id, stored_hash = row
            self.check(
                category,
                "password is persisted as a hash",
                stored_hash != self.password and len(stored_hash) >= 40,
                f"hash_length={len(stored_hash)}; plaintext_match={stored_hash == self.password}",
            )

        profile = await client.get(
            f"{self.base}{AUTH}/me",
            headers={"Cookie": cookie_header(issued)},
        )
        roles = (
            profile.json().get("data", {}).get("roles", []) if profile.status_code == 200 else []
        )
        self.check(
            category,
            "extra admin role fields cannot elevate the registered account",
            profile.status_code == 200 and "SYS_ADMIN" not in roles and "STUDENT" in roles,
            f"HTTP {profile.status_code}; returned_roles={','.join(map(str, roles))[:80]}",
        )

        duplicate = await client.post(
            f"{self.base}{AUTH}/register",
            json={**base_payload, "password": "Different-Password-1!"},
            headers=self.mutation_headers(token, cookies, self.origin),
        )
        duplicate_code, duplicate_message = response_error(duplicate)
        self.check(
            "WSTG-IDNT-02 / WSTG-ATHN-07",
            "duplicate username remains unique",
            duplicate.status_code == 409 and duplicate_code == "USERNAME_TAKEN",
            f"HTTP {duplicate.status_code}; code={duplicate_code}",
        )
        duplicate_disclosed = duplicate_code == "USERNAME_TAKEN" or (
            "用户名已被使用" in (duplicate_message or "")
        )
        self.check(
            "WSTG-IDNT-04",
            "duplicate registration does not disclose account existence",
            not duplicate_disclosed,
            f"HTTP {duplicate.status_code}; specific_duplicate_error={duplicate_disclosed}",
        )

        weak_payload = {
            "username": self.weak_username,
            "password": "password",
            "real_name": "OWASP weak password probe",
            "college_id": self.college_id,
        }
        weak_response = await client.post(
            f"{self.base}{AUTH}/register",
            json=weak_payload,
            headers=self.mutation_headers(token, cookies, self.origin),
        )
        weak_created = weak_response.status_code == 201
        self.check(
            category,
            "common password is rejected by policy",
            not weak_created,
            f"HTTP {weak_response.status_code}; weak_password_accepted={weak_created}",
        )

    async def account_enumeration_suite(self, client: httpx.AsyncClient) -> None:
        category = "WSTG-IDNT-04"
        if self.user_id is None:
            self.check(
                category,
                "active fixture account is available",
                False,
                "registration fixture unavailable",
            )
            return
        existing_times: list[float] = []
        missing_times: list[float] = []
        failures: list[tuple[int, str | None, str | None]] = []
        for index in range(9):
            started = time.perf_counter()
            response, _ = await self.login(
                client, self.base, self.origin, self.username, "Wrong-Password-9!"
            )
            existing_times.append(time.perf_counter() - started)
            failures.append((response.status_code, *response_error(response)))
            started = time.perf_counter()
            missing, _ = await self.login(
                client,
                self.base,
                self.origin,
                f"{self.username}-missing-{index}",
                "Wrong-Password-9!",
            )
            missing_times.append(time.perf_counter() - started)
            failures.append((missing.status_code, *response_error(missing)))

        codes = {status for status, _, _ in failures}
        error_codes = {code for _, code, _ in failures}
        messages = {message for _, _, message in failures}
        self.check(
            category,
            "existing and nonexistent users share failure status and message",
            codes == {401} and error_codes == {"INVALID_CREDENTIALS"} and len(messages) == 1,
            f"statuses={sorted(codes)}; codes={sorted(str(x) for x in error_codes)}; "
            f"message_variants={len(messages)}",
        )
        active_median = statistics.median(existing_times)
        missing_median = statistics.median(missing_times)
        ratio = max(active_median, missing_median) / max(min(active_median, missing_median), 0.0001)
        timing_pass = ratio < 2.0
        self.check(
            category,
            "median invalid-login timing has no 2x account-existence signal",
            timing_pass,
            f"existing_median_ms={active_median * 1000:.1f}; "
            f"missing_median_ms={missing_median * 1000:.1f}; ratio={ratio:.2f}",
        )

        await self.set_user_status(0)
        disabled, disabled_cookies = await self.login(
            client, self.base, self.origin, self.username, self.password
        )
        disabled_code, disabled_message = response_error(disabled)
        disabled_auth_cookie = bool(
            disabled_cookies.get(ACCESS_COOKIE) or disabled_cookies.get(REFRESH_COOKIE)
        )
        self.check(
            category,
            "disabled account shares generic failure response and receives no auth cookies",
            disabled.status_code == 401
            and disabled_code == "INVALID_CREDENTIALS"
            and disabled_message in messages
            and ACCESS_COOKIE not in disabled_cookies
            and REFRESH_COOKIE not in disabled_cookies,
            f"HTTP {disabled.status_code}; code={disabled_code}; "
            f"auth_cookies={disabled_auth_cookie}",
        )
        await self.set_user_status(1)

    async def csrf_suite(self, client: httpx.AsyncClient) -> None:
        category = "WSTG-SESS-05"
        token, cookies = await self.csrf(client, self.base, self.origin)
        cases = (
            (
                "missing CSRF header rejected",
                {"Origin": self.origin, "Cookie": cookie_header(cookies)},
            ),
            (
                "forged CSRF header rejected",
                self.mutation_headers(token, cookies, self.origin)
                | {"X-CSRF-Token": "forged-token"},
            ),
            (
                "untrusted Origin rejected",
                self.mutation_headers(token, cookies, "https://attacker.invalid"),
            ),
        )
        for name, headers in cases:
            response = await client.post(
                f"{self.base}{AUTH}/login",
                json={"username": self.username, "password": self.password},
                headers=headers,
            )
            values, _ = cookie_values(response)
            auth_cookie = bool(values.get(ACCESS_COOKIE) or values.get(REFRESH_COOKIE))
            self.check(
                category,
                name,
                response.status_code == 403
                and ACCESS_COOKIE not in values
                and REFRESH_COOKIE not in values,
                f"HTTP {response.status_code}; auth_cookies={auth_cookie}",
            )

    async def cookie_suite(self, client: httpx.AsyncClient) -> None:
        category = "WSTG-SESS-02 / WSTG-ATHN-01"
        response, cookies = await self.login(
            client, self.base, self.origin, self.username, self.password
        )
        values, attrs = cookie_values(response)
        expected = {
            ACCESS_COOKIE: (f"{API_PREFIX}", 15 * 60),
            REFRESH_COOKIE: (f"{AUTH}", 7 * 24 * 60 * 60),
            CSRF_COOKIE: (f"{API_PREFIX}", 7 * 24 * 60 * 60),
        }
        flags_ok = response.status_code == 200 and all(name in values for name in expected)
        details: list[str] = []
        for name, (path, _) in expected.items():
            item = attrs.get(name, {})
            flags_ok = flags_ok and item.get("httponly") != "" and item.get("secure") != ""
            flags_ok = (
                flags_ok and item.get("samesite", "").lower() == "lax" and item.get("path") == path
            )
            try:
                flags_ok = flags_ok and int(item.get("max-age", "0")) > 0
            except ValueError:
                flags_ok = False
            details.append(
                f"{name}:path={item.get('path')};secure={bool(item.get('secure'))};httponly={bool(item.get('httponly'))};samesite={item.get('samesite')}"
            )
        self.check(
            category,
            "Access, Refresh, and CSRF cookies have expected flags, paths, and positive lifetimes",
            flags_ok,
            f"HTTP {response.status_code}; " + "; ".join(details),
        )

        cache_control = response.headers.get("cache-control", "").lower()
        self.check(
            category,
            "authentication response disables caching",
            "no-store" in cache_control,
            f"Cache-Control={cache_control or '<missing>'}",
        )
        scheme = urlparse(self.base).scheme
        self.check(
            category,
            "credential transport uses HTTPS at the deployment edge",
            True if scheme == "https" else None,
            "HTTPS was used"
            if scheme == "https"
            else (
                "UNVERIFIED outside local HTTP test listener; check the staging/production ingress"
            ),
        )
        self.check(
            category,
            "HSTS is present on the HTTPS deployment edge",
            None,
            "not verifiable on the isolated local HTTP listener; inspect the deployed TLS edge",
        )
        if cookies:
            self.remember_session(cookies)

    async def jwt_suite(self, client: httpx.AsyncClient) -> None:
        category = "WSTG-SESS-10"
        response, cookies = await self.login(
            client, self.base, self.origin, self.username, self.password
        )
        access = cookies.get(ACCESS_COOKIE)
        if response.status_code != 200 or not access:
            self.check(category, "valid JWT fixture issued", False, f"HTTP {response.status_code}")
            return
        try:
            claims = jwt.decode(
                access,
                options={"verify_signature": False, "verify_exp": False},
                algorithms=["HS256"],
            )
        except jwt.PyJWTError:
            self.check(category, "issued JWT can be inspected", False, "token format invalid")
            return
        expected = {"sid", "type", "jti", "iss", "aud", "iat", "exp"}
        safe_payload = not (
            {"username", "user_id", "role", "roles", "permissions", "password"} & set(claims)
        )
        self.check(
            category,
            "JWT contains only the expected session claims and no identity/role data",
            set(claims) == expected and safe_payload,
            f"claim_names={','.join(sorted(claims))}; "
            f"unexpected_identity_claims={not safe_payload}",
        )

        async def token_status(token: str) -> int:
            result = await client.get(
                f"{self.base}{AUTH}/me",
                headers={"Cookie": f"{ACCESS_COOKIE}={token}"},
            )
            return result.status_code

        parts = access.split(".")
        signature = parts[2]
        changed = ("A" if signature[0] != "A" else "B") + signature[1:]
        tampered = ".".join([parts[0], parts[1], changed])
        self.check(
            category,
            "tampered signature rejected",
            await token_status(tampered) == 401,
            "HTTP status checked",
        )

        none_token = (
            b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
            + "."
            + b64url(json.dumps(claims).encode())
            + "."
        )
        self.check(
            category,
            "alg=none token rejected",
            await token_status(none_token) == 401,
            "HTTP status checked",
        )

        variants: list[tuple[str, dict[str, Any]]] = []
        for name, value in (
            ("wrong issuer", {**claims, "iss": "https://issuer.invalid"}),
            ("wrong audience", {**claims, "aud": "untrusted-client"}),
            ("wrong token type", {**claims, "type": "refresh"}),
            (
                "expired token",
                {**claims, "iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600},
            ),
        ):
            variants.append((name, value))
        for required in sorted(expected):
            variants.append(
                (
                    f"missing {required} claim",
                    {key: value for key, value in claims.items() if key != required},
                )
            )
        for name, payload in variants:
            forged = jwt.encode(payload, self.jwt_secret, algorithm="HS256")
            self.check(
                category,
                f"{name} rejected",
                await token_status(forged) == 401,
                "HTTP status checked",
            )

        refresh = cookies.get(REFRESH_COOKIE, "")
        self.check(
            category,
            "Refresh Token cannot authenticate as Access Token",
            await token_status(refresh) == 401,
            "HTTP status checked",
        )

    async def session_suite(self, client: httpx.AsyncClient) -> None:
        category = "WSTG-SESS-06 / WSTG-SESS-07 / WSTG-SESS-11"
        first, first_cookies = await self.login(
            client, self.base, self.origin, self.username, self.password
        )
        if first.status_code != 200:
            self.check(
                category, "valid fixture login available", False, f"HTTP {first.status_code}"
            )
            return
        original_sid = first_cookies[REFRESH_COOKIE].split(".", 1)[0]
        csrf_token = str(first.json().get("data", {}).get("csrf_token", ""))
        headers = self.mutation_headers(csrf_token, first_cookies, self.origin)
        rotated = await client.post(f"{self.base}{AUTH}/refresh", json={}, headers=headers)
        rotated_cookies, _ = cookie_values(rotated)
        self.remember_session(rotated_cookies)
        refresh_changed = rotated_cookies.get(REFRESH_COOKIE) != first_cookies.get(REFRESH_COOKIE)
        self.check(
            category,
            "refresh rotates the token while preserving its session id",
            rotated.status_code == 200
            and rotated_cookies.get(REFRESH_COOKIE) != first_cookies.get(REFRESH_COOKIE)
            and rotated_cookies.get(REFRESH_COOKIE, "").split(".", 1)[0] == original_sid,
            f"HTTP {rotated.status_code}; refresh_changed={refresh_changed}",
        )
        replay = await client.post(
            f"{self.base}{AUTH}/refresh",
            json={},
            headers=self.mutation_headers(csrf_token, first_cookies, self.origin),
        )
        replay_code, _ = response_error(replay)
        stale_access = await client.get(
            f"{self.base}{AUTH}/me",
            headers={"Cookie": f"{ACCESS_COOKIE}={rotated_cookies.get(ACCESS_COOKIE, '')}"},
        )
        self.check(
            category,
            "replayed refresh token is rejected and revokes the rotated session",
            replay.status_code == 401
            and replay_code == "REFRESH_REUSED"
            and stale_access.status_code == 401,
            f"replay_http={replay.status_code}; code={replay_code}; "
            f"new_access_after_replay={stale_access.status_code}",
        )

        logout_login, logout_cookies = await self.login(
            client, self.base, self.origin, self.username, self.password
        )
        logout_csrf = str(logout_login.json().get("data", {}).get("csrf_token", ""))
        copied_access = logout_cookies.get(ACCESS_COOKIE, "")
        logout = await client.post(
            f"{self.base}{AUTH}/logout",
            json={},
            headers=self.mutation_headers(logout_csrf, logout_cookies, self.origin),
        )
        second_client = self.client()
        try:
            copied_cookie = await second_client.get(
                f"{self.base}{AUTH}/me",
                headers={"Cookie": f"{ACCESS_COOKIE}={copied_access}"},
            )
        finally:
            await second_client.aclose()
        self.check(
            category,
            "logout revokes a copied pre-logout access cookie server-side",
            logout_login.status_code == 200
            and logout.status_code == 200
            and copied_cookie.status_code == 401,
            f"login_http={logout_login.status_code}; logout_http={logout.status_code}; "
            f"copied_cookie_http={copied_cookie.status_code}",
        )

        expiry_login, expiry_cookies = await self.login(
            client, self.base, self.origin, self.username, self.password
        )
        expiry_csrf = str(expiry_login.json().get("data", {}).get("csrf_token", ""))
        expiry_sid = expiry_cookies.get(REFRESH_COOKIE, "").split(".", 1)[0]
        if expiry_login.status_code == 200 and expiry_sid:
            await self.redis_main.hset(
                f"lab:v2:auth:session:{expiry_sid}",
                "expires_at",
                str(int(time.time()) - 1),
            )
            expired_refresh = await client.post(
                f"{self.base}{AUTH}/refresh",
                json={},
                headers=self.mutation_headers(expiry_csrf, expiry_cookies, self.origin),
            )
            expired_access = await client.get(
                f"{self.base}{AUTH}/me",
                headers={"Cookie": f"{ACCESS_COOKIE}={expiry_cookies.get(ACCESS_COOKIE, '')}"},
            )
            self.check(
                category,
                "server-side expired session rejects refresh and access requests",
                expired_refresh.status_code == 401 and expired_access.status_code == 401,
                f"refresh_http={expired_refresh.status_code}; "
                f"access_http={expired_access.status_code}",
            )
        else:
            self.check(
                category,
                "server-side expired session rejects refresh and access requests",
                False,
                f"fixture_login_http={expiry_login.status_code}",
            )

        race_login, race_cookies = await self.login(
            client, self.base, self.origin, self.username, self.password
        )
        race_csrf = str(race_login.json().get("data", {}).get("csrf_token", ""))

        async def refresh_once() -> httpx.Response:
            race_client = self.client()
            try:
                return await race_client.post(
                    f"{self.base}{AUTH}/refresh",
                    json={},
                    headers=self.mutation_headers(race_csrf, race_cookies, self.origin),
                )
            finally:
                await race_client.aclose()

        race_responses = await asyncio.gather(refresh_once(), refresh_once())
        race_statuses = sorted(response.status_code for response in race_responses)
        self.check(
            category,
            "concurrent reuse of one refresh token cannot yield two active sessions",
            race_login.status_code == 200 and race_statuses in ([200, 401], [401, 401]),
            f"login_http={race_login.status_code}; refresh_statuses={race_statuses}",
        )

    async def rate_suite(self) -> None:
        category = "WSTG-ATHN-03"
        async with self.client() as client:
            csrf, cookies = await self.csrf(client, self.rate_base, self.rate_origin)
            base_name = f"owasp-rate-{self.run_id}"
            statuses: list[int] = []
            last: httpx.Response | None = None
            for index in range(6):
                variant = base_name.upper() if index % 2 else f"  {base_name}  "
                last = await client.post(
                    f"{self.rate_base}{AUTH}/login",
                    json={"username": variant, "password": "Wrong-Password-9!"},
                    headers=self.mutation_headers(csrf, cookies, self.rate_origin),
                )
                statuses.append(last.status_code)
            retry = (last.headers.get("retry-after", "") if last else "").strip()
            rate_code, _ = response_error(last) if last else (None, None)
            no_token = True
            if last is not None:
                last_cookies, _ = cookie_values(last)
                no_token = ACCESS_COOKIE not in last_cookies and REFRESH_COOKIE not in last_cookies
            try:
                retry_valid = int(retry) >= 1
            except ValueError:
                retry_valid = False
            self.check(
                category,
                "sixth normalized username attempt is throttled with 429 and Retry-After",
                statuses[:5] == [401] * 5
                and statuses[5] == 429
                and rate_code == "RATE_LIMITED"
                and retry_valid
                and no_token,
                f"statuses={statuses}; code={rate_code}; retry_after_present={retry_valid}; "
                f"auth_token_issued={not no_token}",
            )

            async def ip_probe(index: int) -> httpx.Response:
                probe_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(20.0, connect=8.0),
                    trust_env=False,
                )
                try:
                    return await probe_client.post(
                        f"{self.rate_direct_base}{AUTH}/login",
                        json={
                            "username": f"{base_name}-ip-{index}",
                            "password": "Wrong-Password-9!",
                        },
                        headers=self.mutation_headers(csrf, cookies, self.rate_origin)
                        | {"X-Forwarded-For": f"198.51.100.{(index % 200) + 1}"},
                    )
                finally:
                    await probe_client.aclose()

            burst = await asyncio.gather(*(ip_probe(index) for index in range(40)))
            burst_statuses = [response.status_code for response in burst]
            throttled = [response for response in burst if response.status_code == 429]
            forwarded_headers_tested = len(
                {f"198.51.100.{(index % 200) + 1}" for index in range(40)}
            )
            ip_retry_present = bool(throttled and throttled[0].headers.get("retry-after"))
            no_auth_cookie_on_rejections = all(
                ACCESS_COOKIE not in cookie_values(response)[0]
                and REFRESH_COOKIE not in cookie_values(response)[0]
                for response in throttled
            )
            ip_bucket_tokens: list[float] = []
            async for key in self.redis_rate.scan_iter(
                match="lab:v2:rate:policy-v2:login_ip:ip:*:login"
            ):
                state = await self.redis_rate.hgetall(key)
                try:
                    ip_bucket_tokens.append(float(state.get("tokens", "nan")))
                except ValueError:
                    pass
            min_ip_tokens = min(ip_bucket_tokens) if ip_bucket_tokens else None
            self.check(
                category,
                "IP token bucket throttles one peer despite spoofed X-Forwarded-For values",
                bool(throttled)
                and ip_retry_present
                and no_auth_cookie_on_rejections
                and forwarded_headers_tested == 40,
                f"401_count={burst_statuses.count(401)}; 429_count={len(throttled)}; "
                f"distinct_xff={forwarded_headers_tested}; retry_after_present={ip_retry_present}; "
                f"auth_cookie_on_rejected={not no_auth_cookie_on_rejections}; "
                f"ip_bucket_count={len(ip_bucket_tokens)}; min_remaining_tokens={min_ip_tokens}",
            )

    async def bypass_input_suite(self, client: httpx.AsyncClient) -> None:
        category = "WSTG-ATHN-04 / WSTG-INPV-01 / WSTG-INPV-05"
        for path in (f"{AUTH}/me", f"{API_PREFIX}/reservations/mine"):
            response = await client.get(f"{self.base}{path}")
            self.check(
                category,
                f"anonymous direct request to {path} is denied",
                response.status_code == 401,
                f"HTTP {response.status_code}",
            )

        invalid_cookie = await client.get(
            f"{self.base}{AUTH}/me",
            headers={"Cookie": f"{ACCESS_COOKIE}=not-a-jwt"},
        )
        self.check(
            category,
            "malformed access cookie cannot bypass authentication",
            invalid_cookie.status_code == 401,
            f"HTTP {invalid_cookie.status_code}",
        )

        token, cookies = await self.csrf(client, self.base, self.origin)
        probes = (
            "' OR '1'='1",
            "admin'--",
            "x; SELECT SLEEP(1)",
            "control\u0000char",
        )
        probe_outcomes: list[int] = []
        server_error = False
        for value in probes:
            response = await client.post(
                f"{self.base}{AUTH}/login",
                json={"username": value, "password": "Wrong-Password-9!"},
                headers=self.mutation_headers(token, cookies, self.origin),
            )
            probe_outcomes.append(response.status_code)
            if response.status_code >= 500:
                text = response.text.lower()
                server_error = server_error or any(
                    marker in text
                    for marker in ("traceback", "sqlalchemy", "operationalerror", "select ")
                )
        self.check(
            category,
            "SQL/control-character login probes never produce server errors or stack traces",
            all(status in (401, 422) for status in probe_outcomes) and not server_error,
            f"statuses={probe_outcomes}; internal_error_detail={server_error}",
        )

        oversized = await client.post(
            f"{self.base}{AUTH}/login",
            json={"username": "u" * 65, "password": "Wrong-Password-9!"},
            headers=self.mutation_headers(token, cookies, self.origin),
        )
        self.check(
            category,
            "oversized username is rejected by request validation",
            oversized.status_code == 422,
            f"HTTP {oversized.status_code}",
        )

    async def make_openapi_scope(self, client: httpx.AsyncClient) -> None:
        response = await client.get(f"{self.base}{API_PREFIX}/openapi.json")
        if response.status_code != 200:
            self.check(
                "ZAP",
                "OpenAPI available for read-only ZAP API scan",
                False,
                f"HTTP {response.status_code}",
            )
            return
        spec = response.json()
        allowed = {f"{AUTH}/colleges", f"{AUTH}/me"}
        paths = spec.get("paths", {})
        spec["paths"] = {
            path: {
                method: operation
                for method, operation in methods.items()
                if method.lower() == "get"
            }
            for path, methods in paths.items()
            if path in allowed and "get" in methods
        }
        spec["servers"] = [{"url": self.base}]
        destination = self.report_dir / "auth-readonly-openapi.json"
        destination.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        self.check(
            "ZAP",
            "generated read-only OpenAPI scope excludes all mutation paths",
            set(spec["paths"]).issubset(allowed) and len(spec["paths"]) > 0,
            f"read_only_paths={','.join(sorted(spec['paths']))}",
        )

    async def zap_alerts(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.get(
                f"{self.zap_api}/JSON/core/view/alerts/",
                params={"apikey": self.zap_key},
            )
        if response.status_code != 200:
            self.check("ZAP", "ZAP passive alerts retrieved", False, f"HTTP {response.status_code}")
            return []
        raw = response.json().get("alerts", [])
        safe_fields = ("alert", "risk", "confidence", "url", "cweid", "wascid", "pluginId")
        alerts = [{field: item.get(field) for field in safe_fields} for item in raw]
        (self.report_dir / "zap-alerts-sanitized.json").write_text(
            json.dumps(alerts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.check("ZAP", "ZAP passive alerts retrieved", True, f"alert_count={len(alerts)}")
        return alerts

    async def cleanup(self) -> None:
        try:
            async with self.session_factory() as session:
                fixture_ids = list(
                    (
                        await session.scalars(
                            select(User.id).where(
                                User.username.in_([self.username, self.weak_username])
                            )
                        )
                    ).all()
                )
                if fixture_ids:
                    await session.execute(
                        delete(user_roles).where(user_roles.c.user_id.in_(fixture_ids))
                    )
                    await session.execute(delete(User).where(User.id.in_(fixture_ids)))
                    await session.commit()
                if self.user_id is None and fixture_ids:
                    self.user_id = int(fixture_ids[0])
            for redis_client in (self.redis_main, self.redis_rate):
                async for key in redis_client.scan_iter(match="lab:v2:rate:policy-v2:*"):
                    await redis_client.delete(key)
            if self.user_id is not None:
                key = f"lab:v2:auth:user-sessions:{self.user_id}"
                await self.redis_main.delete(key)
            for sid in self.session_ids:
                await self.redis_main.delete(f"lab:v2:auth:session:{sid}")
                async for key in self.redis_main.scan_iter(
                    match=f"lab:v2:auth:session:{sid}:permissions:*"
                ):
                    await self.redis_main.delete(key)
        finally:
            await self.redis_main.aclose()
            await self.redis_rate.aclose()
            await self.engine.dispose()

    def write_report(self, alerts: list[dict[str, Any]]) -> Path:
        grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in CATEGORIES}
        for item in self.checks:
            category = item["category"]
            if category in grouped:
                grouped[category].append(item)
        summary: dict[str, str] = {}
        for key, items in grouped.items():
            states = {item["status"] for item in items}
            summary[key] = (
                "NOT RUN"
                if not items
                else "FAIL"
                if "FAIL" in states
                else "PARTIAL"
                if "UNVERIFIED" in states
                else "PASS"
            )
        payload = {
            "run_id": self.run_id,
            "wstg_version": "4.2 / latest test IDs",
            "started_at_utc": self.started_at.isoformat(),
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "scope": ["/api/v2/auth/*", "/api/v2/reservations/mine (anonymous check)"],
            "summary": summary,
            "checks": self.checks,
            "zap_passive_alerts": alerts,
            "sensitive_values_recorded": False,
        }
        destination = self.report_dir / f"wstg-auth-{self.run_id}.json"
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return destination


async def main() -> int:
    run = WstgRun()
    alerts: list[dict[str, Any]] = []
    client = run.client()
    try:
        await run.registration_suite(client)
        await run.csrf_suite(client)
        await run.account_enumeration_suite(client)
        await run.cookie_suite(client)
        await run.jwt_suite(client)
        await run.session_suite(client)
        await run.bypass_input_suite(client)
        await run.rate_suite()
        await run.make_openapi_scope(client)
        alerts = await run.zap_alerts()
    except Exception as exc:  # noqa: BLE001 - keep infrastructure failures in the report
        run.check(
            "RUN", "runner completed without infrastructure exception", False, type(exc).__name__
        )
    finally:
        await client.aclose()
        await run.cleanup()

    report = run.write_report(alerts)
    for item in run.checks:
        print(f"{item['status']}: {item['category']} — {item['name']} ({item['evidence']})")
    print(f"REPORT: {report}")
    return 1 if any(item["status"] == "FAIL" for item in run.checks) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
