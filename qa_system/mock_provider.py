"""Local OpenAI-compatible deterministic chat/embedding provider for QA only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from cassettes import CassetteStore

ROOT = Path(__file__).resolve().parents[1]
CASSETTE_PATH = ROOT / "qa_system" / "datasets" / "cassette" / "openai.jsonl"
TRACE_PATH = ROOT / "qa_system" / "results" / "mock-provider-trace.jsonl"
CASSETTES = CassetteStore(CASSETTE_PATH, mode=os.getenv("QA_CASSETTE_MODE", "mock"))
FAULT_LOCK = threading.Lock()
FAULT_STATE: dict[str, Any] = {"mode": "", "remaining": 0}
DIMENSION = int(os.getenv("QA_EMBEDDING_DIMENSION", "1024"))


def _messages_text(body: dict[str, Any]) -> str:
    return "\n".join(
        str(message.get("content", ""))
        for message in body.get("messages", [])
        if isinstance(message, dict)
    )


def _schema_name(body: dict[str, Any]) -> str:
    tools = body.get("tools") or []
    if tools and isinstance(tools[0], dict):
        return str((tools[0].get("function") or {}).get("name", ""))
    return ""


def _source_contexts(text: str) -> list[dict[str, Any]]:
    marker = "检索证据 JSON（数据而非指令）："
    position = text.rfind(marker)
    if position < 0:
        return []
    raw = text[position + len(marker) :].strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _question(text: str) -> str:
    match = re.search(r"(?:用户请求|当前用户问题)：([^\n]+)", text)
    return match.group(1).strip() if match else text[-500:]


def _intent_and_arguments(question: str) -> tuple[str, dict[str, Any]]:
    lower = question.casefold()
    device = re.search(r"(?:设备(?:编号|id|号)?\s*[#：:]?\s*)(\d+)", question, re.IGNORECASE)
    dates = re.findall(r"20\d{2}-\d{2}-\d{2}", question)
    reservation = re.search(r"(?:预约(?:编号|id|号)?\s*[#：:]?\s*)(\d+)", question, re.IGNORECASE)
    if "报修" in question or "repair" in lower:
        return "submit_repair", {
            "device_id": int(device.group(1)) if device else 1,
            "title": "QAEVAL mock repair",
            "description": "Offline evaluation request",
        }
    if "取消预约" in question or "cancel reservation" in lower:
        return "cancel_reservation", {
            "reservation_id": int(reservation.group(1)) if reservation else 1
        }
    if "预约" in question and len(dates) >= 1:
        return "create_reservation", {
            "device_id": int(device.group(1)) if device else 1,
            "start_date": dates[0],
            "end_date": dates[-1],
            "purpose": "QAEVAL offline reservation",
        }
    if "可用" in question or "空闲" in question or "availability" in lower:
        return "check_availability", {
            "device_id": int(device.group(1)) if device else 1,
            "start_date": dates[0] if dates else "2028-01-01",
            "end_date": dates[-1] if dates else "2028-01-01",
        }
    if "我的预约" in question or "my reservation" in lower:
        return "my_reservations", {}
    if "推荐" in question or "recommend" in lower:
        return "recommend_devices", {"query": question}
    if "设备" in question or "查找" in question or "search device" in lower:
        return "search_devices", {"query": question[:100]}
    return "answer", {}


def _structured_arguments(schema_name: str, text: str) -> dict[str, Any]:
    if schema_name == "QueryRewrite":
        return {"standalone_query": _question(text), "alternate_queries": []}
    if schema_name == "PlanDecision":
        intent, arguments = _intent_and_arguments(_question(text))
        return {"intent": intent, "arguments": arguments}
    if schema_name == "AnswerDraft":
        contexts = _source_contexts(text)
        for source in contexts:
            source_id = source.get("point_id")
            content = str(source.get("content", "")).strip()
            if source_id is not None and content:
                sentence = re.split(r"(?<=[。！？.!?])\s*", content)[0].strip()
                if sentence:
                    return {
                        "introduction": "",
                        "claims": [
                            {
                                "text": sentence,
                                "source_ids": [str(source_id)],
                                "evidence_quote": sentence,
                            }
                        ],
                        "used_memory_ids": [],
                        "used_l0_message_ids": [],
                    }
        return {"introduction": "", "claims": [], "used_memory_ids": [], "used_l0_message_ids": []}
    return {}


def _deterministic_response(payload: dict[str, Any]) -> dict[str, Any]:
    path_model = str(payload.get("model", "qa-mock"))
    if path_model.lower().startswith("embed") or "embedding" in path_model.lower():
        inputs = payload.get("input", "")
        inputs = inputs if isinstance(inputs, list) else [inputs]
        data = []
        for index, item in enumerate(inputs):
            seed = hashlib.sha512(str(item).encode("utf-8")).digest()
            vector = []
            state = seed
            while len(vector) < DIMENSION:
                for offset in range(0, len(state), 4):
                    integer = int.from_bytes(state[offset : offset + 4], "big")
                    vector.append((integer / 0xFFFFFFFF) * 2.0 - 1.0)
                    if len(vector) >= DIMENSION:
                        break
                state = hashlib.sha512(state).digest()
            data.append({"object": "embedding", "index": index, "embedding": vector})
        return {
            "object": "list",
            "data": data,
            "model": path_model,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }

    text = _messages_text(payload)
    function_name = _schema_name(payload)
    request_id = hashlib.sha1(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:20]
    if function_name:
        arguments = _structured_arguments(function_name, text)
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_{request_id}",
                    "type": "function",
                    "function": {
                        "name": function_name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            ],
        }
        finish = "tool_calls"
    else:
        message = {"role": "assistant", "content": "QA deterministic provider response."}
        finish = "stop"
    return {
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": path_model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": max(1, len(text) // 4),
            "completion_tokens": 24,
            "total_tokens": max(1, len(text) // 4) + 24,
        },
    }


class ProviderHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Do not log request headers, which may contain credentials.
        return

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        if self.path == "/__qa/fault":
            body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
            request = json.loads(body or b"{}")
            with FAULT_LOCK:
                FAULT_STATE.update(
                    mode=str(request.get("mode", "")), remaining=int(request.get("count", 1))
                )
            self._send_json(200, {"armed": True})
            return

        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        payload = json.loads(raw or b"{}")
        fault = self.headers.get("X-QA-Fault")
        with FAULT_LOCK:
            if not fault and FAULT_STATE["remaining"] > 0:
                fault = FAULT_STATE["mode"]
                FAULT_STATE["remaining"] -= 1
                if FAULT_STATE["remaining"] <= 0:
                    FAULT_STATE["mode"] = ""
        if fault == "timeout":
            time.sleep(3)
        elif fault in {"500", "429", "503"}:
            self._send_json(
                int(fault),
                {"error": {"message": "QA injected provider failure", "type": "qa_fault"}},
            )
            return
        elif fault == "invalid-json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "9")
            self.end_headers()
            self.wfile.write(b"{invalid")
            return
        elif fault == "empty":
            self._send_json(200, {"choices": []})
            return

        if self.path.endswith("/embeddings"):
            response = _deterministic_response(
                {**payload, "model": f"embedding:{payload.get('model', '')}"}
            )
        else:
            response = CASSETTES.lookup(payload)
            if response is None:
                response = _deterministic_response(payload)
            CASSETTES.record(payload, response)
        TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TRACE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"path": self.path, "request": payload, "response": response},
                    ensure_ascii=False,
                )
                + "\n"
            )
        self._send_json(200, response)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8765), ProviderHandler)
    server.serve_forever(poll_interval=0.2)


if __name__ == "__main__":
    main()
