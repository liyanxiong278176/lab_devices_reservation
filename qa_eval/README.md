# Independent QA evaluation workspace

This workspace contains new test assets. It does not import or execute anything from
`backend/tests`, `frontend/e2e`, project benchmark folders, or `backend/scripts/e2e_fixture.py`.
The seed factory imports production ORM metadata only to create and remove uniquely named local
fixtures. It never drops a schema or truncates a table.

## Environment

Run from the repository root in PowerShell. Use a local development/test database only. The
the project root `.env` remains untouched; set QA variables in the current PowerShell process. The fixture
factory generates a random disposable password for its accounts and stores it only in the ignored
fixture manifest. The DSN and credentials are consumed only by the process and are redacted from
reports.

```powershell
python -m venv qa_eval\.venv
qa_eval\.venv\Scripts\python -m pip install -U pip
qa_eval\.venv\Scripts\python -m pip install -r qa_eval\requirements.txt

$env:QA_BASE_URL = "http://127.0.0.1:8000"
$env:QA_MYSQL_DSN = "mysql+asyncmy://.../lab_reservation?charset=utf8mb4"
$env:QA_REDIS_URL = "redis://127.0.0.1:6379/0"
$env:QA_FIXTURE_FILE = "qa_eval/results/fixture.json"
qa_eval\.venv\Scripts\python qa_eval\seed_factory.py create
qa_eval\.venv\Scripts\python -m pytest qa_eval\api_tests -q
```

The fixture manifest contains ephemeral test credentials and is ignored by Git. Do not copy it to
the report. After evaluation, call `seed_factory.py cleanup`; if the test process is interrupted,
run cleanup with the same manifest before another run.

## Server

The application under test must be running at `QA_BASE_URL`, with MySQL schema migrated to the
repository's current Alembic head and Redis available. Start the web UI separately at port 5173 for
browser evaluation. The suite will not run Alembic, reset containers, or alter `.env`.

For the 10/50/100 connected-stream benchmark only, use a dedicated local process so the shared
development API and Redis are never stopped or flushed. Start a second FastAPI instance on port
8003 with `LAB_ENVIRONMENT=local`, `LAB_ENABLE_WORKERS=false`,
`LAB_NOTIFICATION_SSE_MAX_PENDING=100`, `LAB_NOTIFICATION_SSE_MAX_PENDING_PER_IP=100`,
`LAB_RATE_LIMIT_ENABLED=false`, and the same local MySQL/Redis endpoints. The relay starts in
`local` mode; background workers remain disabled because the probe drives only its own Outbox rows.
The raised per-IP limit is isolated to the benchmark process. Stop only that process when the probe
is complete.

## Test sequence

1. Create the fixture with `seed_factory.py create` and run `pytest qa_eval/api_tests -q`.
2. Run `probe_concurrency.py` and `probe_redis_fallback.py`; both use real MySQL and isolated QA
   principals. The latter points its own lock/auth clients at an unused local port and never stops
   the shared Redis service.
3. Run the fresh browser spec using `qa_eval/e2e/pw.config.ts`; it creates separate browser
   contexts for students, two college scopes, a lab manager, and a system administrator.
4. Run `probe_pagination.py --repetitions 3`, `probe_cache.py`, and the dedicated `probe_sse_fanout.py`.
   The pagination probe stores uniquely tagged 1k/10k/100k cohorts under the fixture's three
   performance accounts. `seed_factory.py cleanup` removes all fixture-owned rows afterwards.
5. Run the profiles from `profiles.ps1`. The Locust shape stops a profile when it has at least 50
   requests and reaches 3% errors or 1.5s aggregate P95; inspect that stage and stop before further
   load. Soak runs are bounded to at least 30 minutes.

The full test matrix and expected outcomes are in [TEST_PLAN.md](TEST_PLAN.md). Copy the final
measurements into [REPORT_TEMPLATE.md](REPORT_TEMPLATE.md); raw measurements belong under
`qa_eval/results/` and must not include account passwords, cookies, JWTs, session IDs, or DSNs.

## Performance commands

Run from the repository root in PowerShell after setting the QA-only environment variables and
creating the fixture. Start conservatively; do not launch multiple profiles simultaneously.

```powershell
./qa_eval/profiles.ps1 -Profile load -Users 10 -DurationSeconds 30
./qa_eval/profiles.ps1 -Profile stairs -StageSeconds 30
./qa_eval/profiles.ps1 -Profile stress -StageSeconds 25
./qa_eval/profiles.ps1 -Profile spike
./qa_eval/profiles.ps1 -Profile soak -Users 50 -DurationSeconds 1800

$env:QA_BASE_URL = 'http://127.0.0.1:8001'
qa_eval\.venv\Scripts\python qa_eval\probe_pagination.py --repetitions 3
qa_eval\.venv\Scripts\python qa_eval\probe_cache.py
$env:QA_SSE_BASE_URL = 'http://127.0.0.1:8003'
qa_eval\.venv\Scripts\python qa_eval\probe_sse_fanout.py
```

Each profile writes Locust CSV/HTML/logs and a JSONL system sampler file. Locust's aggregate
latencies include authentication; use the per-request CSV rows for endpoint-specific SLO decisions.

## Results

All generated CSV, logs, screenshots, traces, videos, fixture manifests, and reports belong under
`qa_eval/results/`. Reports must redact passwords, cookies, JWTs, session IDs, and database DSNs.
