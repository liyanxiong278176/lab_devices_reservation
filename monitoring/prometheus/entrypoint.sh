#!/bin/sh
set -eu

: "${PROMETHEUS_METRICS_TOKEN:?PROMETHEUS_METRICS_TOKEN must be set}"
umask 077
printf '%s' "$PROMETHEUS_METRICS_TOKEN" > /tmp/lab_metrics_token
unset PROMETHEUS_METRICS_TOKEN

exec /bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --storage.tsdb.retention.time="${PROMETHEUS_RETENTION:-30d}"
