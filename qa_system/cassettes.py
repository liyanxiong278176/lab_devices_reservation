"""Small exact-match JSONL cassette store for deterministic offline requests."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any


def canonical_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_key(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload(payload).encode("utf-8")).hexdigest()


class CassetteStore:
    def __init__(self, path: Path, *, mode: str = "mock") -> None:
        if mode not in {"mock", "record", "replay"}:
            raise ValueError("cassette mode must be mock, record, or replay")
        self.path = path
        self.mode = mode
        self._lock = threading.Lock()

    def lookup(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self.mode != "replay":
            return None
        if not self.path.exists():
            raise LookupError("cassette file does not exist")
        key = payload_key(payload)
        with self._lock:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("key") == key:
                    return item["response"]
        raise LookupError(f"no cassette response for request {key[:12]}")

    def record(self, payload: dict[str, Any], response: dict[str, Any]) -> None:
        if self.mode != "record":
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"key": payload_key(payload), "request": payload, "response": response}
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
