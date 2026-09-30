# FastAPI backend

This is the project's only backend runtime: FastAPI, async SQLAlchemy, MySQL, Redis, and Qdrant. API routes use `/api/v2`.

## Local services and processes

1. Configure the two environment files. From the repository root, copy the Compose secrets template and set the MySQL passwords:

   ```powershell
   Copy-Item .env.example .env
   ```

   Then copy the backend runtime template and set `LAB_MYSQL_DSN` to use the same application password, plus the AI provider credentials needed by the workflows you use:

   ```powershell
   Copy-Item backend/.env.example backend/.env
   ```

   The root `.env` is read by Compose; when API and Worker commands run from `backend`, the backend `.env` is read by FastAPI/Celery.
2. Start the dependencies from the repository root:

   ```powershell
   docker compose up -d mysql redis qdrant
   ```

3. Install backend dependencies and apply the additive migration:

   ```powershell
   cd backend
   uv sync
   uv run alembic upgrade head
   ```

4. Start the API in one terminal:

   ```powershell
   uv run uvicorn app.main:app --loop app.core.uvicorn_loop:platform_loop_factory --reload --port 8000
   ```

5. Start a Celery Worker in another terminal, from `backend`:

   ```powershell
   uv run celery -A app.infrastructure.tasks.celery_app:celery_app worker --pool=solo --loglevel=INFO --concurrency=1 --prefetch-multiplier=1 --queues=knowledge-build
   ```

   `--pool=solo` keeps this local command usable on Windows. In Linux deployments, Celery's prefork pool is appropriate; keep concurrency aligned with the Worker's memory limit and measure peak RSS before increasing it.

6. Start the frontend in another terminal:

   ```powershell
   cd frontend
   pnpm install
   pnpm dev
   ```

The API process also runs the existing SQL Outbox worker. That worker publishes committed document-build records to Celery; the separate Celery Worker consumes them. For a production Docker deployment, the `celery-worker` service shares the `app_data` volume with the API. Any multi-host deployment must mount the same durable upload directory into every API and Worker host: this repository does not currently have object storage. Do not run production Workers against a host-local upload path that they cannot see.

Redis uses database 0 for application sessions/cache and database 1 for Celery. The development compose service enables AOF with `appendfsync everysec` and `noeviction`; it has no artificial memory ceiling. The production compose service reserves 96 MiB of Redis memory within a 128 MiB container limit, leaving room for process overhead; monitor memory and rejected writes before increasing this limit. Celery has no result backend: MySQL build-job rows are the authoritative status. Broker visibility is 7,260 seconds, above the 7,200-second hard task limit; the soft limit is 7,140 seconds. One Worker process with prefetch 1 bounds simultaneous PDF/OCR and Embedding work. The production memory limit is 768 MiB. These are conservative starting values, not workload benchmarks; tune them from observed RSS, build duration, provider latency, and queue age.

## Document build lifecycle

`POST /api/v2/ai/knowledge/upload` validates the user's scope and the file signature, writes the file beneath `LAB_UPLOAD_DIR/ai-knowledge`, then commits the file asset, knowledge document, build-job row, and Outbox row together. It returns HTTP 202 with `document_id`, `job_id`, and `task_id`. The message published to Redis contains only `job_id` and the Celery task ID; the Worker loads the document, tenant, version, and file path from MySQL.

The Outbox closes the database-to-broker gap: the upload transaction cannot commit the document without also recording its pending dispatch. If Redis is unavailable, Outbox retries with bounded exponential backoff; after its configured attempts it marks the job visibly failed. The SQL reconciler republishes a dispatch with a fresh fencing task ID if a queued publication disappears or a Worker lease goes stale. Re-delivery is expected; Celery is not treated as exactly-once. Stable `(document, version, chunk index)` point IDs and SQL uniqueness make repeated writes idempotent.

Build status is stored in MySQL and returned by:

```text
GET /api/v2/ai/knowledge/{document_id}/build-jobs/{job_id}
```

The query checks both the current user's knowledge-management scope and the job's document, job ID, and college association. The knowledge panel refreshes its list every five seconds while a build is queued, processing, or retrying. The response includes stage, progress units, attempts, safe failure summary, and timestamps. When a queued task is blocked by a failed predecessor, the response also identifies that earliest failed job so an authorized manager can act on the actual blocker.

Builds use strict FIFO within each document, based on a durable per-document sequence. Tasks for different documents can still publish and run concurrently. The SQL Outbox checks predecessor state before publishing, so blocked jobs remain in SQL rather than being repeatedly requeued into Celery. The Worker repeats the predecessor check as a safety net for deliveries already in flight during a rollout. A predecessor in `QUEUED`, `PROCESSING`, `RETRYING`, or `FAILED` state blocks every later build for that document. `COMPLETED`, `CANCELLED`, and explicitly `SKIPPED` jobs release the sequence.

An authorized manager can retry a failed job at `POST /api/v2/ai/knowledge/{document_id}/build-jobs/{job_id}/retry`. The same business job row and sequence are reused, while a fresh Celery task ID fences out stale deliveries. A failed job from a superseded document version cannot be retried; it must be explicitly skipped. Use `POST /api/v2/ai/knowledge/{document_id}/build-jobs/{job_id}/skip` with a 2–500 character reason to release that failed sequence position. LAB_ADMIN can act only within their college; SYS_ADMIN can act across colleges. Skip records the actor, timestamp, and reason, and marks only the task `SKIPPED`; it does not mark the document successful or change its active index. The UI explains this before the manager confirms.

The Outbox worker exposes bounded Prometheus gauges for job counts by status, pending publication count, same-document order waiters, oldest SQL build wait, Outbox pending/processing age, recent completion throughput and failure ratio, Redis ready and unacked message counts, oldest unacked age, and Redis metric availability. These appear in the provisioned **LabFlow Knowledge Build Queue** Grafana dashboard. The queue and SQL values are sampled by the API Outbox process; in a multi-API deployment dashboards use `max` for these shared-state gauges to avoid counting the same database/broker depth once per API replica. A zero-valued queue metric is not proof of an empty queue when `ai_knowledge_build_queue_metrics_available` is zero.

For an initial production response to rising queue depth or job age, inspect the oldest job and task stage, provider latency/failure rate, Worker RSS, and Redis availability. The current production Worker is deliberately limited to one concurrent build under a 768 MiB container limit. After observing peak memory and sustained build throughput, scale Worker replicas manually while keeping per-process concurrency at one:

```powershell
docker compose -f docker-compose.prod.yml up -d --scale celery-worker=2
```

This command changes the example to two Worker containers; choose a replica count that matches measured memory and downstream API capacity. There are no autoscaling thresholds yet because this repository has no representative production load baseline. Alert thresholds and scaling policy should be set after collecting queue age, arrival rate, completion rate, failure rate, provider latency, and per-Worker RSS under real workloads.

For PDF uploads the Worker first runs PyMuPDF in a worker thread using sorted page text. The existing repository had no parser-quality scoring rules or thresholds for column order or formula fidelity, so the implementation does not invent one: it falls back to MinerU when PyMuPDF fails, returns no usable text, or emits the Unicode replacement character. MinerU calls use finite timeouts and a maximum 20-minute polling window. Non-PDF Office and image files continue to use MinerU. A failed/corrupt current-version document can be resubmitted through the existing `/parse` route; when a later job is waiting behind a failed predecessor, use the specific retry or skip actions shown on the document card.

After parsing, the Worker reuses the existing DLP and section-aware chunking code, embeds bounded batches, and writes version-tagged points and SQL rows. Documents still require the existing human review and explicit publish action. Rebuilds write into a new version; retrieval filters Qdrant and SQL by the active published version. Publishing switches the MySQL `active_version` pointer after the full build and review are complete, then schedules old-version cleanup. A failed build therefore leaves the prior published version available.

`0035_ai_knowledge_build_jobs` adds the durable job table and version columns, and backfills current published-document pointers and chunk versions. `0036_knowledge_build_ordering` adds and backfills per-document sequence numbers, indexes the FIFO gate and queue state queries, and adds skip audit fields. Do not edit already-applied migrations; apply new revisions with Alembic.

Upgrade to an empty MySQL 8 schema and the live workspace schema both succeed. A disposable-database downgrade check exposed a rollback defect in revision 0035: MySQL refuses to drop the `college_id` index while the build-job foreign key still depends on it. The project rule forbids editing this already-applied revision, so do not use `alembic downgrade 0034_notification_sequence` until a separately reviewed rollback correction is available.

## Online RAG behavior

The online answer path continues to use async SQLAlchemy, the async Qdrant client, async Embedding/LLM clients, and `httpx.AsyncClient` for hosted Rerank. Dense vector and Qdrant BM25 lanes run concurrently under `LAB_AI_RAG_QUERY_CONCURRENCY` (default 4); SQL lexical reads remain sequential on the same `AsyncSession`, then existing RRF and Rerank logic combine the results. The current tenant, role, resource-scope, and active-version filters are applied before vector search where Qdrant can enforce them and are rechecked against live SQL records before citations are returned. Rerank remains best-effort and async. No Celery task is waited on by an online answer request.

## Common checks

```powershell
cd backend
uv run ruff check .
uv run pytest -q
```

```powershell
cd frontend
pnpm build
pnpm test
```

For a real Web + Redis Broker + Celery Worker + Qdrant smoke test, run this after MySQL is at Alembic head and the local Redis and Qdrant services are healthy:

```powershell
cd backend
uv run python scripts/smoke_knowledge_build_worker.py
```

The script starts a temporary Uvicorn API and a separate Celery Worker process, uses deterministic test Embeddings instead of paid model APIs, uploads a generated PDF, waits for the MySQL job to complete, reviews and publishes it, then verifies the published chunk through live hybrid retrieval. It deletes its temporary database rows, file, and Qdrant collection. The configured Qdrant server must be version 1.19.0, matching the repository Compose image; older 1.14.1 servers in this workspace returned `InferenceService is not initialized` for the existing Qdrant BM25 write path. If your current Qdrant is older, start an isolated compatible instance in a separate terminal:

```powershell
docker run --rm --name qdrant-19-smoke -p 127.0.0.1:6334:6333 qdrant/qdrant:v1.19.0
```

Then point the smoke script at it:

```powershell
$env:LAB_QDRANT_URL='http://127.0.0.1:6334'
uv run python scripts/smoke_knowledge_build_worker.py
```

The MySQL concurrency integration test for same-document Outbox ordering is opt-in and must point at an isolated MySQL 8 database already migrated to head with one seeded user and college:

```powershell
$env:LAB_TEST_MYSQL_DSN = "mysql+asyncmy://<test-user>:<test-password>@127.0.0.1:3306/<isolated-test-database>?charset=utf8mb4"
uv run pytest -q tests/test_mysql_knowledge_build_ordering.py
Remove-Item Env:LAB_TEST_MYSQL_DSN
```

It creates uniquely named temporary documents and removes its own Outbox/job/document rows in `finally`. Keep this test database separate from production data.

Reservation concurrency acceptance remains covered by `benchmarks/reservation_concurrency.py`: a single device/date collision must produce one success and `409` for the rest.
