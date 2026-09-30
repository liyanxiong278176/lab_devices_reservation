# Independent multi-user evaluation plan

This plan is for the new `qa_eval/` harness only. It does not import or execute project tests,
existing Playwright specs, benchmark scripts, or fixture factories. API/integration tests use a real
FastAPI process, MySQL 8, and Redis; browser tests use fresh Playwright BrowserContexts. AI routes
are excluded from inventory and workload.

## Preconditions and evidence

- Current schema is already at Alembic head `0034_notification_sequence`; this evaluation never
  runs migrations or changes existing migration files.
- The local QA API, MySQL, Redis, and frontend are healthy before each run. Environment variables
  are set in the current PowerShell process; `.env` is not edited.
- `seed_factory.py` creates unique colleges, labs, devices, students, managers, system admin, SSE,
  and performance principals. Cleanup selects only recorded IDs and fixture-specific asset paths.
- The generated endpoint inventory is `route_inventory.md`. It comes from the API OpenAPI schema
  with AI endpoints removed and records method, path, authentication, tenant scope, and fields.
- Evidence (JUnit, Locust CSV/HTML, JSON probes, Playwright trace/screenshots, telemetry) stays in
  `results/`; account credentials, cookies, session IDs, JWTs, and DSNs must not be copied to reports.

## Functional, error, boundary, and security matrix

| ID | Layer | Scenario | Expected result |
|---|---|---|---|
| API-F01 | Interface + MySQL integration | Create date-only reservation with a required approval path | HTTP 201; one reservation/day rows; `PENDING`; a due notification Outbox task exists |
| API-F02 | Interface + MySQL integration | Create reservation without approval requirement | HTTP 201; expected direct approval state and no duplicate day rows |
| API-F03 | Interface + MySQL integration | Manager approves/rejects; user cancels a still-cancellable request | Only legal state transitions succeed; repeated/competing transition returns conflict; audit/outbox facts are not duplicated |
| API-F03a | Interface + MySQL concurrency | Manager approval races student cancellation | Exactly one HTTP 200 and one 409; fresh MySQL read matches the winning terminal/active status and occupied-day count |
| API-F04 | Interface + MySQL integration | Attempt self check-in before manager handover | HTTP 409 `HANDOVER_REQUIRED`; no state change |
| API-F05 | Interface + MySQL integration | Handover, first-day check-in, end-day return and inspection | State reaches `COMPLETED`; timestamps/checklist and notification history are persisted |
| API-F05a | Interface + MySQL integration | Mark an approved reservation as violated | Status is `VIOLATED`, occupied days are released, and one -20 credit event is persisted |
| API-F05b | Outbox + MySQL integration | Advance the due time of an isolated no-show task and execute through the production worker | Status is `NO_SHOW`, occupied days are released, one -10 credit event is persisted, task reaches `COMPLETED` |
| API-F06 | Interface + MySQL integration | Create repair report, manager takes/resolves, student confirms | Lifecycle is persisted in order; device availability follows repair state |
| API-F07 | Interface + MySQL integration | Reserve a maintenance device | HTTP 409 `RESERVATION_CONFLICT`; no occupied day is inserted |
| API-B01 | Interface | Start date after end date; empty required purpose | HTTP 422; no reservation rows |
| API-B02 | Interface + MySQL integration | Same date, partial overlap, adjacent interval, same request replay | Overlap is rejected; adjacent dates are allowed; same idempotency key returns the original reservation and creates no second day row |
| API-B03 | Interface | Past date, maximum duration, cross-month/year/leap-day boundary | Service's date-only validation is applied consistently; invalid ranges are rejected with a stable 4xx response |
| API-B04 | Interface | Page 0, page 1, high page, and skip beyond 100,000 | Page 0 and excessive skip return 422; valid pages are stable and scoped before ID pagination |
| API-S01 | Interface + authorization database check | Anonymous request; cross-college device/reservation/report access | Anonymous requests return 401; tenant escape returns 403/404; no row is changed |
| API-S02 | Interface + authorization database check | Write without cookie, missing/wrong CSRF, untrusted Origin | Request is denied before the business write; database row counts remain unchanged |
| API-S03 | Security integration | Login SID rotation/high entropy across 50+ logins; refresh rotation and old-token replay | New sessions use unique high-entropy SIDs; replayed refresh is rejected and revokes the rotated session |
| API-S04 | Security integration | Logout with open SSE | Stream receives `auth-revoked` and closes; subsequent protected request fails |
| API-N01 | Interface + MySQL integration | SSE reconnect with `Last-Event-ID`; 101 queued notifications | The newest 100 rows replay in sequence, summary reports one omitted row and HTTP history contains the full set |
| API-N02 | Interface + MySQL integration | Notification history and read/unread state | HTTP history remains authoritative; user sees only own/tenant-visible rows |

The exact assertions and current API case names are in `api_tests/`. Tests identify themselves in
docstrings as interface or integration tests. There are no fake repositories in the concurrency
probes.

## Real-MySQL concurrency matrix

| ID | Race | Expected result and fresh-connection check |
|---|---|---|
| RACE-01 | 50 and 100 independent sessions reserve one device/day with different idempotency keys | Exactly one 201; remaining requests are 409 `RESERVATION_CONFLICT`; a new connection reads exactly one occupied day |
| RACE-02 | Partial-overlap intervals compete | At most one overlapping claim wins; no duplicate `(device_id, date)` rows |
| RACE-03 | Adjacent intervals and different devices compete | Adjacent day and distinct device reservations can both succeed |
| RACE-04 | Redis lock service unavailable during a booking race | DB unique constraint still selects exactly one winner; an unauthenticated request fails closed with session-store error |
| RACE-05 | Duplicate/competing transitions | Exactly one legal conditional transition persists; audit and notification rows are checked from a new DB session |
| RACE-06 | Outbox duplicate consumption | Only one worker claims a task at a time; unique task key creates one notification; completed task cannot create a second notification |
| RACE-07 | Two independent OutboxWorker instances race on one due notification row | Exactly one `SKIP LOCKED` claimant; repeated handler execution leaves one notification with one delivery sequence |

The lock fallback uses an isolated unused localhost port. It does not stop or flush shared Redis.

## Multi-user browser flow

`e2e/multi_user_full_chain.spec.ts` creates separate browser contexts for two CSE students, a BIO
student, a CSE manager, and a system admin. It verifies:

1. Login and dashboard navigation for each role.
2. Two ordinary users competing for a same-day device reservation; only one gets the occupied day.
3. Ordinary-user menu and direct-route restrictions, plus system-admin cross-college access.
4. Manager approval/handover; SSE proxy disconnect/reconnect; the reconnect carries the last event ID,
   replay updates notification history/unread summary, and the user completes return inspection.
5. Student repair report, manager take/resolve, student confirmation, and final visible status.

Assertions cover visible text, URLs, status tags, row counts, and notification summary. Failure trace
and screenshots are retained under `results/e2e-artifacts/`.

## Performance plan and stop rules

SLO starting points: normal authenticated read API P95 < 300ms, P99 < 800ms, and normal-profile
error rate < 0.1%. These are evaluation thresholds, not an availability guarantee. Do not continue
increasing pressure after the first observed saturation/failure breakpoint.

| Profile | Planned load | Expected observation |
|---|---|---|
| Load | Separate 10/25/50/100/200-user runs | Per-endpoint RPS, P50/P90/P95/P99, failure percentage, 503 count, CPU/RSS, MySQL pool/threads, Redis clients/memory |
| Stairs | 10 → 25 → 50 → 100 → 200; configurable hold per stage | Stage where latency/failure begins to rise; stop shape at first threshold |
| Stress | 25 → 50 → 100 → 150 → 200 → 250 | Saturation point; graceful 429/503 rather than cascading timeout; then health/recovery check |
| Spike | 10 → 100 in 30 seconds, hold, return to 10 | Recovery time, errors during burst, no orphaned task or damaged data |
| Soak | 50 users for at least 30 minutes | RSS/connection trend, error drift, cache and response-time drift |
| Pagination | 1k/10k/100k rows; page 1 and deepest reachable page; three samples per strategy | Full-row OFFSET vs ID-page+join direct SQL and live API medians |
| Cache | Unique QA catalog key; three cache misses and three hits; isolated unreachable Redis cache client | Response content remains identical; hit latency/DB query reduction; cache service falls back to MySQL |
| SSE | 10/50/100 concurrent streams; five tabs for each of 2/10/20 QA users; three repetitions | Every tab receives the committed event; same per-user sequence on all tabs; record median/P95/max push latency |

`profiles.ps1` writes locust CSV/HTML and the telemetry JSONL file. The Locust shape terminates a
profile after at least 50 requests if aggregate failure ratio reaches 3% or aggregate P95 reaches
1,500ms; it also stops at 90% host memory usage. These are stop rules, not permission to keep
applying load. Soak is limited to the local QA environment and can be stopped if host memory or
database health degrades.

## Cleanup and recovery

After collecting outputs, run `seed_factory.py cleanup` using the same fixture manifest. It removes
only fixture-owned rows and asset files. Verify account/device/college counts for recorded IDs are
zero; verify Redis keys by exact fixture namespace. If cleanup is interrupted, keep the ignored
manifest and rerun cleanup before deleting the manifest. Stop only QA processes started on 8001,
8002, 8003, and 5174 by their recorded process IDs; leave user-owned ports and containers alone.
