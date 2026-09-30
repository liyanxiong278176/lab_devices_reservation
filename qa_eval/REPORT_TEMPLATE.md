# Multi-user QA evaluation report

> Run ID: `YYYYMMDD-xxxxx`  
> Date/time and timezone:  
> Commit/revision:  
> Environment: local isolated schema; no production credentials in this file  
> API/UI endpoints:  
> Schema head: `0034_notification_sequence`

## Executive result

- Overall: `PASS / PASS WITH LIMITATIONS / FAIL`
- Test environment health before/after:
- Scenarios passed / failed / blocked:
- High-severity defects found, fixed, and re-tested:
- Residual risks and unexecuted scenarios:
- Fixture cleanup verification:

## Endpoint and functional/security coverage

Use `route_inventory.md` for the full method/path/request/response inventory. Record the exact test
result and link to raw JUnit/log evidence here.

| Area | Cases | Passed | Failed | Expected/actual summary | Evidence |
|---|---:|---:|---:|---|---|
| Functional lifecycle | | | | | |
| Invalid input and date boundaries | | | | | |
| Tenant isolation and authorization | | | | | |
| Cookie, CSRF, Origin, login and refresh | | | | | |
| SSE reconnect, replay cap, history and logout | | | | | |
| Browser UI multi-role flow | | | | | |

## Defect loop

| Case / severity | Stable reproduction and expected vs actual | Root cause (`file:line`) | Minimal fix | Regression result |
|---|---|---|---|---|
| | | | | |

## Concurrency and consistency

| Race | Competition size | Expected | Actual | Fresh-connection DB count/state | Result/evidence |
|---|---:|---|---|---|---|
| Same device/day | 50 | 1 success, remaining 409 | | | |
| Same device/day | 100 | 1 success, remaining 409 | | | |
| Partial overlap | | at most one overlapping winner | | | |
| Adjacent dates / distinct devices | | both independent bookings may succeed | | | |
| Redis lock unavailable | | same DB invariant; auth fail-closed | | | |
| Transition/Outbox worker race | | one legal state, one notification | | | |

## Performance results

### Load and capacity

| Profile/stage | Users | RPS | P50 ms | P90 ms | P95 ms | P99 ms | Error % | HTTP 503 count | CPU / peak RSS | MySQL connections/threads | Redis clients/memory | Recovery |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|
| | | | | | | | | | | | | |

Report the first error/latency breakpoint, largest stage meeting the declared SLO, whether
overload produced bounded 429/503 behavior, and health/data-integrity results after load. If the
host reaches its safety threshold first, record the run as host-limited rather than app-capacity.

### Data volume and deep pagination (at least three samples; show medians)

| Rows | Page | Full-row OFFSET median ms | ID-page + join median ms | Actual API median ms | Optimization vs baseline |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 1 / deepest | | | | |
| 10,000 | 1 / deepest | | | | |
| 100,000 | 1 / deepest | | | | |

### Cache and Redis fallback

| Mode | Samples | Median ms | MySQL query delta | Redis hit/miss delta | Content/correctness |
|---|---|---:|---:|---:|---|
| API cache miss | | | | | |
| API cache hit | | | | | |
| Cache client Redis unavailable | | | | N/A | authoritative MySQL fallback |
| Reservation lock Redis unavailable | | | | N/A | one database winner; auth fails closed |

### SSE connected fanout (three repetitions per profile)

| Concurrent streams | Users / tabs per user | Delivered / expected | Median push ms | P95 push ms | Max ms | Sequence / duplicate check |
|---:|---|---:|---:|---:|---:|---|
| 10 | 2 × 5 | | | | | |
| 50 | 10 × 5 | | | | | |
| 100 | 20 × 5 | | | | | |

## Evidence and cleanup

- API JUnit XML/log:
- Playwright JUnit, screenshots, trace/video:
- Concurrency and Redis-fallback JSON:
- Locust CSV/HTML and telemetry JSONL:
- Pagination/cache/SSE JSON:
- MySQL/Redis health before and after:
- QA processes stopped by exact PID:
- Fixture records/files/keys removed by exact IDs:

Do not attach `fixture.json`; it contains ephemeral account credentials.
