# ADR 0037: AI knowledge build FIFO and backlog observability

- Status: Accepted
- Date: 2026-09-30

## Context

Document builds may rebuild parser output, embeddings, and search indexes. Independent documents should use Worker capacity concurrently, while builds for the same document must not race over staged rows or document state. A failed build must remain actionable without allowing later versions to overtake it silently. The system already persists build jobs and dispatch intent in MySQL Outbox rows, then uses Celery with Redis as the work broker.

## Decision

Assign every build a monotonically increasing `sequence` while locking its document row. Keep the sequence on the business job row. Before publishing a build from SQL Outbox to Celery, check for a lower sequence in `QUEUED`, `PROCESSING`, `RETRYING`, or `FAILED`. Leave later dispatches pending in SQL and mark the job stage `WAITING_ORDER`. A final Worker-side gate protects deliveries that were already published during rolling deployment or recovery.

Keep strict FIFO per document and allow builds for different documents to run concurrently. Do not send blocked jobs to Celery for immediate retry: this keeps ordering policy in the durable source and avoids broker churn. A bounded second check after delivery can acknowledge an already-in-flight duplicate and record one durable Outbox wake-up rather than looping in Celery.

An authorized manager can retry a failed job in place. Retrying keeps the row and sequence, clears failure/progress state, creates a fresh Celery task ID, and adds a new SQL Outbox publication row. Retrying an obsolete document version is rejected because the Worker correctly fences builds whose version no longer matches the document.

An authorized manager can explicitly skip only a failed job after supplying a reason. The endpoint records `skipped_by`, `skipped_at`, and `skip_reason`; LAB_ADMIN is limited to their college and SYS_ADMIN may act across colleges. Skipping changes only that job to `SKIPPED`. It does not make the document successful or move the active index pointer. A newer job may then proceed in sequence.

Expose SQL job counts, order waiters, oldest job age, Outbox age, Redis ready/unacked counts and age, recent throughput, failure ratio, and Redis metric availability. Provision a Grafana dashboard for these signals. Scale the existing single-concurrency Worker replicas manually after collecting representative memory, duration, and throughput data; no autoscaling threshold is chosen without a production baseline.

## Consequences

- Same-document builds are strictly serialized, even if their PDF, Embedding, or model calls could otherwise overlap.
- A failed predecessor intentionally pauses that document until a manager retries or skips it; unrelated documents continue to build.
- A retried job is still at-least-once work. Stable versioned point IDs, SQL uniqueness, task fencing, and idempotent writes remain required; Celery does not provide end-to-end exactly-once business effects.
- Explicit skip is auditable and preserves the last published index, but the document remains in its existing business state until a later build succeeds or an operator takes another action.
- Queue depth alone cannot show a queue problem. Operators can compare SQL wait age, Redis ready/unacked depth, throughput, failures, and Worker resource use.
- Worker replica scaling is simple to operate but remains a manual action until load data supports a safe automated policy.
