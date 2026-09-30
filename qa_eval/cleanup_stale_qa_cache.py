"""Remove only stale catalog entries created from qa_eval's exact fixture naming scheme."""

from __future__ import annotations

import asyncio
import json
import re

from config import REDIS_URL
from redis.asyncio import Redis

CATALOG_KEY = re.compile(r"^lab:v2:catalog:devices:college:(\d+):v\d+:[0-9a-f]{24}$")
QA_DEVICE = re.compile(r"^qa-device-([0-9a-f]{10})-(?:cse|bio)-\d{2}$")


async def cleanup() -> dict[str, object]:
    client = Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
    keys_to_remove: set[str] = set()
    version_keys: set[str] = set()
    run_ids: set[str] = set()
    try:
        async for key in client.scan_iter(match="lab:v2:catalog:devices:college:*", count=200):
            match = CATALOG_KEY.fullmatch(key)
            if match is None:
                continue
            raw = await client.get(key)
            if raw is None:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            items = payload.get("items", []) if isinstance(payload, dict) else []
            matched_run_ids = {
                row_match.group(1)
                for item in items
                if isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and (row_match := QA_DEVICE.fullmatch(item["name"])) is not None
            }
            if not matched_run_ids:
                continue
            keys_to_remove.update({key, f"{key}:load-lock"})
            version_keys.add(f"lab:v2:cache:catalog:version:college:{match.group(1)}")
            run_ids.update(matched_run_ids)

        keys_to_remove.update(version_keys)
        removed = 0
        for start in range(0, len(keys_to_remove), 500):
            batch = list(keys_to_remove)[start : start + 500]
            removed += int(await client.delete(*batch)) if batch else 0
        remaining = [
            key
            async for key in client.scan_iter(match="lab:v2:catalog:devices:college:*")
            if key in keys_to_remove
        ]
        if remaining:
            raise RuntimeError(f"stale QA catalog keys remain: {len(remaining)}")
        return {"removed_keys": removed, "matched_fixture_run_ids": sorted(run_ids)}
    finally:
        await client.aclose()


def main() -> None:
    print(json.dumps(asyncio.run(cleanup()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
