# ADR 0033: Prometheus and Grafana runtime observability

- Status: Accepted
- Date: 2026-09-26

## Context

The application had a protected health endpoint but no durable time-series metrics or operator dashboard. Runtime diagnosis needs API latency/error/throughput, process and SQLAlchemy pool usage, MySQL/Redis health, container resources, and asynchronous Outbox worker activity. Reservation and repair business KPIs are outside this dashboard's scope.

## Decision

Use Prometheus for scraping and 30-day time-series retention, Grafana for local-only visualization, the MySQL and Redis exporters for dependency metrics, and cAdvisor for container metrics. Provision the datasource and a technical-runtime dashboard from version-controlled configuration. Start these services with the full development or production Compose stack.

Prometheus has no published host port. Grafana binds only to localhost; development can select a free host port with `GRAFANA_PORT`, while remote production access uses an SSH tunnel. `/api/v2/metrics` remains disabled unless a dedicated 32+ character bearer token is configured. The production Compose injects the same token into the API and Prometheus from the root environment file. MySQL metrics use a dedicated account with exporter-required read-only grants and a connection cap. Credentials are environment-only and are not committed. No Alertmanager or business KPI panels are added.

Application labels use route templates, bounded HTTP methods, and status classes; arbitrary paths and tenant/user identifiers are excluded. The in-process registry enforces a hard series limit. Redis remains optional to business correctness; exporter failure is visible as a scrape failure and does not affect application requests.

## Consequences

- Operators can inspect runtime trends across the API, dependencies, worker, and containers without exposing Prometheus to the host network.
- Metrics storage is bounded by a 30-day retention policy; the Prometheus data volume must be sized for local workload.
- Developers configure both `PROMETHEUS_METRICS_TOKEN` and `LAB_METRICS_TOKEN` in the root `.env` with the same value; production Compose passes the token only to the API and Prometheus services that need it.
- cAdvisor requires read-only access to host/container filesystem and cgroup paths. It is not privileged and its metrics endpoint is not published.
- The dashboard contains technical telemetry only. Alerting and business analytics remain future work.
