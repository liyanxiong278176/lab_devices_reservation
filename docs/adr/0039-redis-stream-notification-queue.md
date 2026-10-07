# ADR 0039: Redis Streams for notification delivery

- Status: Accepted
- Date: 2026-10-01
- Supersedes: the Pub/Sub transport decision in ADR 0036

## Context

The notification table and per-user `delivery_sequence` are durable MySQL facts. SSE is the browser-facing, server-to-client transport. The previous Redis Pub/Sub relay only carried wake-up hints, so messages could not wait in Redis for a process to consume them. Notification creation already originates from the MySQL Outbox; read-state hints previously happened after the database commit and could be lost.

## Decision

Append the complete notification payload and read-state-change events to one Redis Stream from the Outbox worker. Persist read-state Outbox tasks in the same MySQL transaction as the read update. Keep MySQL notification rows and Outbox tasks as the recovery source when Redis is unavailable or loses recent data.

Each API process uses a distinct consumer group. Groups broadcast every Stream entry to every process; consumers inside one process group share work up to the configured bounded concurrency. A newly created group starts at the current Stream tail; an existing group retains lag and pending entries while its process is offline. Configure `LAB_NOTIFICATION_STREAM_GROUP_ID` with a stable, unique value per process when those entries must be recovered by the same group after restart. The default uses hostname and PID and is distinct across concurrently running local processes. When a new group starts, currently connected local SSE streams reconcile pre-existing events from MySQL.

Use at-least-once delivery. ACK a Stream entry only after handing the full event to that process's in-memory SSE Hub. The browser does not ACK SSE. The Hub deduplicates by notification ID and delivery sequence, and the SSE endpoint orders events by `(user_id, delivery_sequence)`. A sequence gap is filled from MySQL before a later event is sent. EventSource reconnect replays from MySQL using `Last-Event-ID`, capped at 100 rows; HTTP history remains the path for older history.

Retry transient consumer handoff failures with exponential backoff and jitter. After five delivery attempts, atomically append the original payload and failure details to the dead-letter Stream and ACK the original entry. Invalid event payloads go directly to dead letter. Prometheus exports Stream length, per-process group lag, oldest queued age, pending count, pending idle age, retry totals, and dead-letter length; alert rules cover old backlog, high lag, and any dead-letter entry.

Do not automatically trim Stream entries. An operator may use the `trim-acked` command, which removes only entries already delivered and ACKed by every existing consumer group. The operator must inspect and remove stale consumer groups through a separately reviewed Redis maintenance action; stale groups can otherwise retain entries indefinitely. DLQ inspection and replay are command-line operations; no admin management API is added.

## Consequences

- A process that is offline accumulates Stream entries for its consumer group and processes them at its configured concurrency after it returns.
- A consumer may hand the same notification to an SSE Hub more than once after an ACK/network failure. Sequence and notification-ID deduplication make those retries harmless.
- If Redis loses recent Stream data, MySQL reconnect replay and sequence-gap recovery remain authoritative; Redis AOF with `appendfsync everysec` and no replica does not promise zero recent-write loss.
- Stream storage can grow until operators run the safe acknowledged-entry trim command. Alerts expose backlog and dead letters, while notification history remains in MySQL.
- Every API process receives every event, which costs one Stream consumer group per process and makes per-process group identity part of operations.

## Operational commands

Run from the `backend` directory with the normal `LAB_REDIS_URL` configuration:

```powershell
uv run python -m app.infrastructure.notifications.stream_ops stats
uv run python -m app.infrastructure.notifications.stream_ops inspect --limit 50
uv run python -m app.infrastructure.notifications.stream_ops replay 1727770000000-0
uv run python -m app.infrastructure.notifications.stream_ops trim-acked --limit 1000
uv run python -m app.infrastructure.notifications.stream_ops destroy-group lab:v2:notification:process:stale-replica --confirm
```

Check that a group is stale before destroying it: this removes its pending list. `trim-acked` is manual and refuses to delete entries that are still unconsumed or pending in any existing group.
