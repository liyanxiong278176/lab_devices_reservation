"""Run Locust at 5/10/25/50/100 virtual users, with three repetitions each."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

QA = Path(__file__).resolve().parent
RESULTS = QA / "results" / "locust"
PROFILES = (5, 10, 25, 50, 100)
REPETITIONS = 3
RUN_SECONDS = 10


def find_aggregate(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return next(row for row in rows if row.get("Name") == "Aggregated")


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, object]] = []
    for users in PROFILES:
        for repetition in range(1, REPETITIONS + 1):
            prefix = RESULTS / f"locust_{users}_{repetition}"
            stats_path = Path(f"{prefix}_stats.csv")
            if not stats_path.exists():
                command = [
                    sys.executable,
                    "-m",
                    "locust",
                    "-f",
                    str(QA / "locustfile.py"),
                    "--headless",
                    "--users",
                    str(users),
                    "--spawn-rate",
                    str(min(users, 20)),
                    "--run-time",
                    f"{RUN_SECONDS}s",
                    "--host",
                    "http://127.0.0.1:8000",
                    "--csv",
                    str(prefix),
                    "--only-summary",
                    "--loglevel",
                    "WARNING",
                ]
                completed = subprocess.run(
                    command,
                    cwd=QA,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=90,
                    check=False,
                )
                (RESULTS / f"locust_{users}_{repetition}.log").write_text(
                    completed.stdout + "\n--- stderr ---\n" + completed.stderr,
                    encoding="utf-8",
                )
                if not stats_path.exists():
                    raise RuntimeError(
                        f"Locust produced no stats at {users} users, repetition {repetition}; "
                        f"see {RESULTS / f'locust_{users}_{repetition}.log'}"
                    )
            aggregate = find_aggregate(stats_path)
            row: dict[str, object] = {
                "users": users,
                "repetition": repetition,
                "requests": int(aggregate.get("Request Count", 0)),
                "failures": int(aggregate.get("Failure Count", 0)),
                "median_ms": aggregate.get("Median Response Time", ""),
                "p95_ms": aggregate.get("95%", ""),
                "rps": aggregate.get("Requests/s", ""),
            }
            summaries.append(row)
            print(
                f"users={users} repetition={repetition} requests={row['requests']} "
                f"failures={row['failures']} median_ms={row['median_ms']} "
                f"p95_ms={row['p95_ms']} rps={row['rps']}",
                flush=True,
            )

    (QA / "results" / "locust-matrix.json").write_text(
        json.dumps(summaries, indent=2), encoding="utf-8"
    )
    report = [
        "# Locust mixed business and AI API profile",
        "",
        f"Headless Locust, {RUN_SECONDS}s per run, read-only endpoints after CSRF-protected login.",
        (
            "The isolated QA API disables request rate limiting only for this capacity profile; "
            "authentication and rate limiting are checked separately."
        ),
        (
            "This fixture-scale run does not represent larger database cardinalities "
            "or production infrastructure."
        ),
        "",
        "| Users | Rep | Requests | Failures | Median ms | p95 ms | RPS |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        report.append(
            (
                "| {users} | {repetition} | {requests} | {failures} | "
                "{median_ms} | {p95_ms} | {rps} |"
            ).format(**row)
        )
    (QA / "results" / "locust-matrix.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
