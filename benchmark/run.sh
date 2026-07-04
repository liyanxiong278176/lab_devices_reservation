#!/usr/bin/env bash
# JMeter load-test wrapper — runs a scenario via the justb4/jmeter docker image.
# Usage: ./benchmark/run.sh <lock|recommend|dashboard>
#
# Env overrides:
#   HOST (default host.docker.internal), PORT (default 8080)
#   DEVICE_ID, LOCK_START, LOCK_END (lock scenario only; default = device 1, tomorrow 14:00-15:00)
#   LOGIN_USER / LOGIN_PASS (recommend/dashboard credential overrides)
set -e

SCN=${1:-}
HOST=${HOST:-host.docker.internal}
PORT=${PORT:-8080}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$ROOT/benchmark/out"

case "$SCN" in
  lock)
    JMX=lock-concurrency
    # GNU date (Git Bash / Linux) first, BSD date (macOS) fallback
    if [ -z "${LOCK_START:-}" ]; then
      LOCK_START=$(date -d "+1 day 14:00" +%Y-%m-%dT14:00:00 2>/dev/null || date -v+1d +%Y-%m-%dT14:00:00)
      LOCK_END=$(date -d "+1 day 15:00" +%Y-%m-%dT15:00:00 2>/dev/null || date -v+1d +%Y-%m-%dT15:00:00)
    fi
    DEVICE_ID=${DEVICE_ID:-1}
    EXTRA=(-JdeviceId="$DEVICE_ID" -JlockStart="$LOCK_START" -JlockEnd="$LOCK_END")
    echo "[lock] device=$DEVICE_ID slot=$LOCK_START..$LOCK_END"
    ;;
  recommend) JMX=recommend-qps;;
  dashboard) JMX=dashboard-qps;;
  *)
    echo "usage: $0 <lock|recommend|dashboard>"
    echo "env: HOST PORT DEVICE_ID LOCK_START LOCK_END LOGIN_USER LOGIN_PASS"
    exit 1
    ;;
esac

echo "[$SCN] target $HOST:$PORT -> benchmark/out/${SCN}.jtl"

docker run --rm \
  -v "$ROOT/benchmark:/benchmark" \
  justb4/jmeter:latest \
  -n -t "/benchmark/jmeter/${JMX}.jmx" \
  -l "/benchmark/out/${SCN}.jtl" \
  -Jhost="$HOST" -Jport="$PORT" \
  "${EXTRA[@]}"

echo "[$SCN] raw results: $ROOT/benchmark/out/${SCN}.jtl"
