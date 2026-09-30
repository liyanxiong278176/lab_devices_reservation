from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_REDACTION = "[已脱敏]"
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "credential",
        re.compile(
            r"(?i)(?:\bsk-[A-Za-z0-9_-]{12,}\b|\bBearer\s+[A-Za-z0-9._~+/=-]{12,}|"
            r"\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret)\s*[:=]\s*"
            r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+))"
        ),
    ),
    (
        "password",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
        ),
    ),
    ("email", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("identity_number", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
)
_SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"authorization|phone|mobile|email|identity|id[_-]?card|credential)"
)


@dataclass(frozen=True)
class DlpResult:
    text: str
    categories: tuple[str, ...]


def redact_text(value: str) -> DlpResult:
    """Redact common credentials and direct identifiers before persistence or model use."""

    text = value
    categories: set[str] = set()
    for category, pattern in _PATTERNS:
        text, replacements = pattern.subn(_REDACTION, text)
        if replacements:
            categories.add(category)
    return DlpResult(text=text, categories=tuple(sorted(categories)))


def redact_value(value: Any) -> tuple[Any, set[str]]:
    """Recursively sanitize model-bound structured data without mutating the source."""

    if isinstance(value, str):
        result = redact_text(value)
        return result.text, set(result.categories)
    if isinstance(value, list):
        output: list[Any] = []
        categories: set[str] = set()
        for item in value:
            safe, item_categories = redact_value(item)
            output.append(safe)
            categories.update(item_categories)
        return output, categories
    if isinstance(value, tuple):
        safe, categories = redact_value(list(value))
        return tuple(safe), categories
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        categories: set[str] = set()
        for key, item in value.items():
            string_key = str(key)
            if _SENSITIVE_KEY.search(string_key):
                output[string_key] = _REDACTION
                categories.add("sensitive_field")
                continue
            safe, item_categories = redact_value(item)
            output[string_key] = safe
            categories.update(item_categories)
        return output, categories
    return value, set()
