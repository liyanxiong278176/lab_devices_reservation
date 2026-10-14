"""Sequential 10k/100k-row factorial study: index, pagination, page depth, SQL/HTTP.

Experimental DDL is permitted only in the disposable lab_resume_* schema.
No hints or forced indexes; the MySQL optimizer must select the covering path.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from app.core.settings import Settings
from app.infrastructure.db.models import Reservation, User
from app.infrastructure.db.pagination import delayed_page_ids
from app.infrastructure.db.session import build_engine, build_session_factory
from benchmarks.http_read_capacity import PAGE_SIZE, authenticate, percentile
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

INDEX = "idx_resume_user_college_id"


def digest(data: object) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def table_nodes(plan: object) -> list[dict]:
    nodes = []
    if isinstance(plan, dict):
        if "table_name" in plan:
            nodes.append(plan)
        for value in plan.values():
            nodes.extend(table_nodes(value))
    elif isinstance(plan, list):
        for value in plan:
            nodes.extend(table_nodes(value))
    return nodes


async def study(args: argparse.Namespace) -> None:
    page_count = args.rows // PAGE_SIZE
    test_pages = (1, page_count // 2, page_count)
    settings = Settings()
    schema = make_url(settings.mysql_dsn).database or ""
    if re.fullmatch(r"lab_resume_[a-f0-9]{8}", schema) is None:
        raise RuntimeError("Study DDL requires a disposable lab_resume_* schema")
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    clients = {
        strategy: httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}/api/v2/",
            timeout=60,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )
        for strategy, port in (("traditional", 8006), ("deferred", 8007))
    }
    args.output.mkdir(parents=True, exist_ok=True)
    samples_path = args.output / "pagination-study-samples.jsonl"
    rounds_path = args.output / "pagination-study-rounds.jsonl"
    samples = []
    evidence = []
    hashes: dict[tuple[str, int], str] = {}

    def check_hash(layer: str, page: int, value: str) -> None:
        key = layer, page
        if key in hashes and hashes[key] != value:
            raise AssertionError(f"Result mismatch: {key}")
        hashes[key] = value

    try:
        async with factory() as session:
            user = await session.scalar(select(User).where(User.username == args.username))
            if user is None:
                raise RuntimeError("Missing study user")
            user_id, college_id = user.id, user.college_id
            conditions = [Reservation.user_id == user_id, Reservation.college_id == college_id]
            actual_rows = await session.scalar(select(func.count()).select_from(Reservation))
            assert actual_rows == args.rows
            assert (
                await session.scalar(
                    select(func.count()).select_from(Reservation).where(*conditions)
                )
                == args.rows
            )

        statements: dict[tuple[str, int], str] = {}
        id_queries: dict[int, str] = {}
        for page in test_pages:
            ids = delayed_page_ids(
                select(Reservation.id).where(*conditions),
                Reservation.id,
                page=page,
                page_size=PAGE_SIZE,
            )
            queries = {
                "traditional": select(Reservation)
                .where(*conditions)
                .order_by(Reservation.id.desc())
                .offset((page - 1) * PAGE_SIZE)
                .limit(PAGE_SIZE),
                "deferred": select(Reservation)
                .join(ids, ids.c.id == Reservation.id)
                .order_by(Reservation.id.desc()),
            }
            for strategy, query in queries.items():
                statements[strategy, page] = str(
                    query.compile(
                        dialect=engine.dialect,
                        compile_kwargs={"literal_binds": True},
                    )
                )
            id_queries[page] = str(
                select(Reservation.id)
                .where(*conditions)
                .order_by(Reservation.id.desc())
                .offset((page - 1) * PAGE_SIZE)
                .limit(PAGE_SIZE)
                .compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True})
            )

        async def prepare_index(mode: str, round_number: int) -> None:
            table = Reservation.__tablename__
            async with engine.connect() as connection:
                indexes = await connection.execute(text(f"SHOW INDEX FROM `{table}`"))
                before = [dict(row) for row in indexes.mappings()]
                exists = any(row["Key_name"] == INDEX for row in before)
                if mode == "covering" and not exists:
                    await connection.execute(
                        text(f"CREATE INDEX `{INDEX}` ON `{table}` (user_id, college_id, id)")
                    )
                elif mode == "current" and exists:
                    await connection.execute(text(f"DROP INDEX `{INDEX}` ON `{table}`"))
                analyzed = await connection.execute(text(f"ANALYZE TABLE `{table}`"))
                analyze_rows = [dict(row) for row in analyzed.mappings()]
                assert any(row["Msg_text"] == "OK" for row in analyze_rows)
                await connection.commit()
                indexes = await connection.execute(text(f"SHOW INDEX FROM `{table}`"))
                after = [dict(row) for row in indexes.mappings()]
                candidate_columns = [
                    row["Column_name"]
                    for row in sorted(after, key=lambda item: item["Seq_in_index"])
                    if row["Key_name"] == INDEX
                ]
                assert candidate_columns == (
                    ["user_id", "college_id", "id"] if mode == "covering" else []
                )
                plans, id_plans = {}, {}
                for page in test_pages:
                    id_result = await connection.execute(
                        text("EXPLAIN FORMAT=JSON " + id_queries[page])
                    )
                    id_plan = json.loads(id_result.scalar_one())
                    nodes = table_nodes(id_plan)
                    covered = any(
                        node.get("key") == INDEX and node.get("using_index") is True
                        for node in nodes
                    )
                    id_plans[str(page)] = {
                        "sql": id_queries[page],
                        "json": id_plan,
                        "candidate_covering_index_selected": covered,
                    }
                    for strategy in clients:
                        sql = statements[strategy, page]
                        result = await connection.execute(text("EXPLAIN FORMAT=JSON " + sql))
                        plan = json.loads(result.scalar_one())
                        actual = await connection.execute(text("EXPLAIN ANALYZE " + sql))
                        plans[f"{strategy}:{page}"] = {
                            "sql": sql,
                            "json": plan,
                            "analyze": [row[0] for row in actual.all()],
                            "candidate_covering_index_selected": any(
                                node.get("key") == INDEX and node.get("using_index") is True
                                for node in table_nodes(plan)
                            ),
                        }
                evidence.append(
                    {
                        "round": round_number,
                        "index_mode": mode,
                        "indexes_before": before,
                        "indexes_after": after,
                        "analyze_table": analyze_rows,
                        "id_subquery_plans": id_plans,
                        "pagination_plans": plans,
                    }
                )
                (args.output / "pagination-study-plans.json").write_text(
                    json.dumps(evidence, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )
                print(
                    json.dumps(
                        {
                            "round": round_number,
                            "index_mode": mode,
                            "statistics_refreshed": True,
                            "id_subquery_covering": {
                                page: value["candidate_covering_index_selected"]
                                for page, value in id_plans.items()
                            },
                        }
                    ),
                    flush=True,
                )

        async def block(layer: str, mode: str, strategy: str, page: int, round_number: int) -> None:
            raw = []

            async def sql_read(connection) -> tuple[float, str, int, int]:
                started = time.perf_counter_ns()
                result = await connection.execute(text(statements[strategy, page]))
                rows = [dict(row) for row in result.mappings()]
                ended = time.perf_counter_ns()
                assert len(rows) == PAGE_SIZE
                return (ended - started) / 1e6, digest(rows), started, ended

            async def http_read() -> tuple[float, str, int, int]:
                started = time.perf_counter_ns()
                response = await clients[strategy].get(
                    "reservations/mine",
                    params={"page": page, "page_size": PAGE_SIZE},
                )
                ended = time.perf_counter_ns()
                response.raise_for_status()
                data = response.json()["data"]
                assert response.status_code == 200
                assert data["total"] == args.rows and data["pages"] == page_count
                assert data["page"] == page and len(data["items"]) == PAGE_SIZE
                return (ended - started) / 1e6, digest(data), started, ended

            async def record(read, requests: int) -> None:
                for _ in range(args.warmup):
                    _, value, _, _ = await read()
                    check_hash(layer, page, value)
                for index in range(requests):
                    latency, value, started, ended = await read()
                    check_hash(layer, page, value)
                    raw.append(
                        {
                            "round": round_number,
                            "layer": layer,
                            "index_mode": mode,
                            "strategy": strategy,
                            "page": page,
                            "offset": (page - 1) * PAGE_SIZE,
                            "request_index": index,
                            "latency_ms": round(latency, 6),
                            "started_ns": started,
                            "completed_ns": ended,
                            "rows_returned": PAGE_SIZE,
                            "data_sha256": value,
                            **({"status": 200} if layer == "http" else {}),
                        }
                    )

            if layer == "sql":
                # Connection checkout/pre-ping and transaction setup are outside SQL timing.
                async with engine.connect() as connection:
                    await record(lambda: sql_read(connection), args.sql_requests)
            else:
                await record(http_read, args.http_requests)
            samples.extend(raw)
            with samples_path.open("a", encoding="utf-8") as output:
                for row in raw:
                    output.write(json.dumps(row) + "\n")
            latencies = [row["latency_ms"] for row in raw]
            summary = {
                "round": round_number,
                "layer": layer,
                "index_mode": mode,
                "strategy": strategy,
                "page": page,
                "samples": len(raw),
                "p50_ms": round(percentile(latencies, 0.5), 3),
                "p95_ms": round(percentile(latencies, 0.95), 3),
                "p99_ms": round(percentile(latencies, 0.99), 3),
            }
            with rounds_path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(summary) + "\n")
            print(json.dumps(summary), flush=True)

        for round_index in range(args.rounds):
            round_number = round_index + 1
            modes = ("current", "covering") if round_index % 2 == 0 else ("covering", "current")
            strategies = (
                ("traditional", "deferred") if round_index % 2 == 0 else ("deferred", "traditional")
            )
            pages = test_pages[round_index % 3 :] + test_pages[: round_index % 3]
            for mode in modes:
                await prepare_index(mode, round_number)
                for client in clients.values():
                    await authenticate(
                        client,
                        username=args.username,
                        password=args.password,
                        origin="http://127.0.0.1:5175",
                    )
                for page in pages:
                    for layer in ("sql", "http"):
                        for strategy in strategies:
                            await block(layer, mode, strategy, page, round_number)

        grouped: dict[tuple, list[float]] = defaultdict(list)
        for row in samples:
            grouped[row["index_mode"], row["layer"], row["page"], row["strategy"]].append(
                row["latency_ms"]
            )
        summary = [
            {
                "index_mode": mode,
                "layer": layer,
                "page": page,
                "strategy": strategy,
                "samples": len(latencies),
                "p50_ms": round(percentile(latencies, 0.5), 3),
                "p95_ms": round(percentile(latencies, 0.95), 3),
                "p99_ms": round(percentile(latencies, 0.99), 3),
            }
            for (mode, layer, page, strategy), latencies in sorted(grouped.items())
        ]
        ordered = sorted(samples, key=lambda row: row["started_ns"])
        overlap = sum(
            right["started_ns"] < left["completed_ns"] for left, right in zip(ordered, ordered[1:])
        )
        assert overlap == 0
        report = {
            "rows": args.rows,
            "actual_rows_verified": actual_rows,
            "concurrency": 1,
            "page_size": PAGE_SIZE,
            "pages": list(test_pages),
            "total_pages": page_count,
            "rounds": args.rounds,
            "http_requests_per_cell_per_round": args.http_requests,
            "sql_requests_per_cell_per_round": args.sql_requests,
            "warmup_per_block": args.warmup,
            "candidate_index": {"name": INDEX, "columns": ["user_id", "college_id", "id"]},
            "index_modes": ["current", "covering"],
            "forced_indexes": False,
            "statistics_refreshed_before_each_phase": True,
            "sql_timing": (
                "buffered main SELECT, client execution, driver roundtrip and row decode; "
                "excludes COUNT, eager loads, auth, connection checkout and serialization"
            ),
            "http_timing": (
                "full authenticated response body; "
                "excludes login, warmup, JSON validation and digest"
            ),
            "overlapping_formal_request_intervals": overlap,
            "formal_sql_requests": sum(row["layer"] == "sql" for row in samples),
            "formal_http_requests": sum(row["layer"] == "http" for row in samples),
            "matching_page_digests": len(hashes),
            "summary": summary,
            "covering_verified_all_phases_and_pages": all(
                page["candidate_covering_index_selected"]
                for phase in evidence
                if phase["index_mode"] == "covering"
                for page in phase["id_subquery_plans"].values()
            ),
            "deferred_covering_verified_all_phases_and_pages": all(
                phase["pagination_plans"][f"deferred:{page}"]["candidate_covering_index_selected"]
                for phase in evidence
                if phase["index_mode"] == "covering"
                for page in test_pages
            ),
        }
        (args.output / "pagination-study.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "completed": True,
                    "sql": report["formal_sql_requests"],
                    "http": report["formal_http_requests"],
                    "overlap": overlap,
                }
            ),
            flush=True,
        )
    finally:
        await asyncio.gather(*(client.aclose() for client in clients.values()))
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--http-requests", type=int, default=250)
    parser.add_argument("--sql-requests", type=int, default=500)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--rows", type=int, choices=(10_000, 100_000), default=10_000)
    args = parser.parse_args()
    if min(args.rounds, args.http_requests, args.sql_requests, args.warmup) < 1:
        parser.error("rounds, sample counts and warmup must be positive")
    asyncio.run(study(args))


if __name__ == "__main__":
    main()
