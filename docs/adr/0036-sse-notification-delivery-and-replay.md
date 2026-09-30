# ADR 0036: SSE notification delivery, replay, and read-state sync

- Status: Accepted
- Date: 2026-09-29

## Context

The application only sends notification updates from the server to browser clients. Persisted MySQL notifications remain the historical source of truth, while Redis Pub/Sub already bridges low-latency events between API processes. A reconnect needs an ordered cursor, bounded catch-up, tenant-aware authorization, and a way to synchronize read state across a user's active tabs.

## Decision

Use Server-Sent Events (SSE) for notification delivery. Authenticate the stream with the current HttpOnly cookie session and derive the user and active college from the server-side principal. The endpoint accepts no user identifier; it validates the request origin, limits pending and active streams, and periodically rechecks session, account, college, and notification permission state.

Add a persistent, unique `(user_id, delivery_sequence)` to each notification. Allocate the next sequence while locking the recipient's user row and commit it in the same transaction as the notification. This makes sequence assignment independent of Outbox worker completion order. Backfill existing rows by user and notification ID when applying the additive Alembic migration.

On a new EventSource connection, start at the current visible per-user sequence head and rely on HTTP history for page reloads or new logins. On the same EventSource's automatic reconnect, use `Last-Event-ID` to replay eligible rows in ascending sequence order. Replay at most 100 notifications per response; if more remain, send the first 100, emit a synchronization summary with the visible high-water sequence, and let the browser refresh notification history and unread count over HTTP. The UI deduplicates by sequence within that EventSource and presents one summary for a replay batch.

After an Outbox notification commits, publish a Redis wake-up hint. Each SSE process then reads notification rows from MySQL by sequence; Pub/Sub arrival order and payload are not delivery truth. Mark-read operations commit in MySQL first and publish a lightweight read-state hint to every active stream for that user, including other tabs and devices. A reconnect or HTTP history request reconciles any missed hint. Tabs maintain independent SSE cursors and toast deduplication.

Disable proxy buffering and caching for the stream route. Keep long-lived streams out of the normal database request-capacity semaphore; enforce explicit stream and pending-connection limits instead.

## Consequences

- Browser-to-server messaging is not available on the notification channel; notification actions continue to use authenticated HTTP endpoints.
- SSE reconnects on the same EventSource can recover missed notifications, while page reloads use the paginated HTTP history API.
- The per-user row lock and unique index enforce strict allocation order across concurrent Outbox workers; Redis remains an acceleration path and cannot break notification history.
- Long offline periods do not create unbounded SSE replay. The notification center and unread count are refreshed through bounded HTTP queries.
- Each tab can independently show one reconnect summary. Read-state changes propagate across all online tabs for that user.
