from __future__ import annotations

import pytest
from cassettes import CassetteStore


def test_record_and_replay_uses_stable_canonical_payload(tmp_path) -> None:
    payload = {"model": "qa-model", "messages": [{"role": "user", "content": "hello"}]}
    response = {"choices": [{"message": {"content": "recorded"}}]}
    store = CassetteStore(tmp_path / "provider.jsonl", mode="record")
    store.record(payload, response)
    replay = CassetteStore(tmp_path / "provider.jsonl", mode="replay")
    assert replay.lookup({"messages": payload["messages"], "model": "qa-model"}) == response


def test_replay_fails_clearly_when_request_is_not_recorded(tmp_path) -> None:
    store = CassetteStore(tmp_path / "empty.jsonl", mode="replay")
    with pytest.raises(LookupError):
        store.lookup({"model": "not-recorded"})
