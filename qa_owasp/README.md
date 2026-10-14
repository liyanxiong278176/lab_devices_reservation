> 2026-10-14：此目录仅保留历史报告。旧可执行脚本及 Python 依赖已删除；下方命令和路径只记录历史实验，当前验证使用 `backend-java/` 和 `frontend/e2e/`。

# OWASP WSTG authentication assessment

This is an independent black-box assessment of the live FastAPI HTTP surface.
It does not import or run `backend/tests` or `frontend/e2e`. Requests pass
through OWASP ZAP; the focused probes are mapped to OWASP Web Security Testing
Guide (WSTG) cases. The ZAP API scan is restricted to read-only `GET` operations
under `/api/v2/auth` so it cannot fuzz reservation, repair, or admin mutations.

## Scope

The runner covers the eight requested areas:

| Area | WSTG mapping |
|---|---|
| Account enumeration | IDNT-04 |
| Login brute force and throttling | ATHN-03 |
| Login CSRF | SESS-05 |
| Cookie flags, HTTPS and HSTS | SESS-02, ATHN-01, CONF-07 |
| JWT validation | SESS-10 |
| Refresh, logout, expiry, replay and concurrent sessions | SESS-06, SESS-07, SESS-11 |
| Registration, password handling and role injection | IDNT-02, ATHN-07 |
| Direct protected-resource requests and input probes | ATHN-04, INPV-01, INPV-05 |

The HTTP probe runner sends authentication and session probes through ZAP's
proxy. The IP bucket burst uses a direct loopback connection so all 40 requests
have one controlled TCP peer; each request varies `X-Forwarded-For` to check
that untrusted forwarding headers cannot split that peer into separate buckets.
ZAP then runs an
API scan against a generated allowlist containing only the read-only
`GET /api/v2/auth/colleges` and `GET /api/v2/auth/me` operations. The ZAP image
and version are printed by the runner and its sanitized findings are kept in
the ignored `results/` directory.

## Run

Prerequisites: Docker Desktop, the project's backend virtual environment, and
the local development MySQL and Redis services. MySQL must already be migrated
to the current Alembic head. The script never runs migrations or stops existing
services. It refuses to proceed if ports 8002, 8003, or 8090 are occupied, or if
Redis logical databases 12 or 13 are non-empty.

From the repository root in PowerShell:

```powershell
./qa_owasp/run.ps1
```

The script starts two temporary API instances on loopback: one with a high
login threshold for enumeration/lifecycle probes, and one with the repository's
default login token-bucket thresholds for brute-force probes. Both use Redis
DB 12 or 13, a generated test-only JWT secret, and `LAB_ENABLE_WORKERS=false`.
Do not point this runner at production or a shared staging environment.

One uniquely named test account is registered through the API; a common
password account is attempted as a separate policy probe. The runner
temporarily disables only its generated account and restores/deletes its own
fixtures in `finally`. It records status codes, WSTG case outcomes, timing
medians, and sanitized ZAP alert metadata. It never writes passwords, Cookie
values, JWTs, session IDs, or database credentials to the report. Runtime logs,
ZAP output, and JSON reports are ignored by Git.

The local listener uses HTTP, so the HTTPS and HSTS cases are explicitly marked
unverified for the deployment edge. Run the same WSTG cases against the actual
staging HTTPS URL before treating those deployment controls as passed.

## WSTG references

- [IDNT-04 Account Enumeration](https://wstg.owasp.org/latest/4-Web_Application_Security_Testing/03-Identity_Management/04-Account_Enumeration_and_Guessable_User_Account/)
- [ATHN-03 Weak Lock Out Mechanism](https://wstg.owasp.org/latest/4-Web_Application_Security_Testing/04-Authentication/03-Weak_Lock_Out_Mechanism/)
- [SESS-05 Cross-Site Request Forgery](https://wstg.owasp.org/stable/4-Web_Application_Security_Testing/06-Session_Management_Testing/05-Testing_for_Cross_Site_Request_Forgery/)
- [SESS-02 Cookie Attributes](https://wstg.owasp.org/stable/4-Web_Application_Security_Testing/06-Session_Management_Testing/02-Testing_for_Cookies_Attributes/)
- [ATHN-01 Credentials over an Encrypted Channel](https://wstg.owasp.org/stable/4-Web_Application_Security_Testing/04-Authentication_Testing/01-Testing_for_Credentials_Transported_over_an_Encrypted_Channel/)
- [SESS-10 JSON Web Tokens](https://wstg.owasp.org/latest/4-Web_Application_Security_Testing/06-Session_Management/10-JSON_Web_Tokens/)
- [SESS-06 Logout Functionality](https://wstg.owasp.org/stable/4-Web_Application_Security_Testing/06-Session_Management_Testing/06-Testing_for_Logout_Functionality/)
- [SESS-07 Session Timeout](https://wstg.owasp.org/stable/4-Web_Application_Security_Testing/06-Session_Management_Testing/07-Testing_for_Session_Timeout/)
- [IDNT-02 User Registration](https://wstg.owasp.org/stable/4-Web_Application_Security_Testing/03-Identity_Management_Testing/02-Test_User_Registration_Process/)
- [ATHN-07 Weak Password Policy](https://wstg.owasp.org/v4.2/4-Web_Application_Security_Testing/04-Authentication_Testing/07-Testing_for_Weak_Password_Policy/)
- [ATHN-04 Authentication Bypass](https://wstg.owasp.org/latest/4-Web_Application_Security_Testing/04-Authentication/04-Bypassing_Authentication_Schema/)
- [ZAP Docker scans](https://www.zaproxy.org/docs/docker/)
