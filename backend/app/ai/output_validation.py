from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.ai.dlp import redact_text


class EvidenceClaim(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    source_ids: list[str] = Field(default_factory=list, max_length=5)
    evidence_quote: str = Field(default="", max_length=2000)


class AnswerDraft(BaseModel):
    introduction: str = Field(default="", max_length=1000)
    claims: list[EvidenceClaim] = Field(default_factory=list, max_length=20)
    used_memory_ids: list[int] = Field(default_factory=list, max_length=100)
    used_l0_message_ids: list[int] = Field(default_factory=list, max_length=100)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


_NEGATION_PATTERN = re.compile(
    r"\b(?:not|never|no|cannot|unavailable|forbidden|prohibited|without)\b"
    r"|不允许|不可以|不能|不得|禁止|未|没|不|无|非",
    re.IGNORECASE,
)
_QUALIFIER_PATTERN = re.compile(
    r"\b(?:may|might|could|possibly|probably|usually|generally|only|if|unless)\b"
    r"|可能|也许|或许|通常|一般|仅|只有|如果|若|除非|暂时|应当|必须|建议",
    re.IGNORECASE,
)
_PROMPT_INJECTION_PATTERN = re.compile(
    r"\b(?:ignore|disregard|override|bypass)\b.{0,48}\b(?:previous|prior|system|developer)\b"
    r".{0,24}\b(?:instructions?|rules?|prompt|policy)\b"
    r"|(?:忽略|无视|覆盖|绕过).{0,16}(?:之前|所有|系统|开发者|安全).{0,12}(?:指令|规则|提示|权限)"
    r"|(?:回答|回复|输出|结尾|末尾).{0,24}(?:追加|包含|附上|输出|泄露).{0,24}(?:金丝雀|CANARY|密钥|token|提示词|密码)",
    re.IGNORECASE,
)
_CANARY_PATTERN = re.compile(r"\bCANARY-[A-Z0-9_-]{4,}\b", re.IGNORECASE)


def _negation_parity(text: str) -> int:
    return len(_NEGATION_PATTERN.findall(text)) % 2


def validate_answer_draft(
    draft: AnswerDraft,
    sources: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], list[int], list[int]]:
    """Keep only claims whose cited source exists and contains the exact evidence.

    Requiring the claim text to be a substring of an exact quoted evidence span is
    intentionally conservative: paraphrases are not treated as proven facts.
    """

    by_id = {
        str(source.get("point_id")): source
        for source in sources
        if source.get("point_id") is not None and source.get("content")
    }
    kept: list[str] = []
    citations: dict[str, dict[str, Any]] = {}
    for claim in draft.claims:
        claim_text = _normalize(claim.text)
        quote = _normalize(claim.evidence_quote)
        if (
            not claim_text
            or not quote
            or _PROMPT_INJECTION_PATTERN.search(claim.text)
            or _PROMPT_INJECTION_PATTERN.search(claim.evidence_quote)
            or _CANARY_PATTERN.search(claim.text)
            or _CANARY_PATTERN.search(claim.evidence_quote)
            or claim_text not in quote
            or _negation_parity(claim_text) != _negation_parity(quote)
            or not set(_QUALIFIER_PATTERN.findall(quote)).issubset(
                set(_QUALIFIER_PATTERN.findall(claim_text))
            )
        ):
            continue
        cited_source = None
        for source_id in claim.source_ids:
            source = by_id.get(str(source_id))
            evidence_texts = (
                str(source.get("content", "")),
                str(source.get("context_content", "")),
            ) if source is not None else ()
            if source is not None and any(quote in _normalize(text) for text in evidence_texts):
                cited_source = source
                break
        if cited_source is None:
            continue
        citation_id = str(cited_source["point_id"])
        kept.append(f"{claim.text} [citation:{citation_id}]")
        citations[citation_id] = cited_source

    claims_text = "\n".join(kept)
    # Model-generated free prose is never displayed: it cannot be tied to an
    # auditable evidence span. Greetings and status messages are produced by
    # deterministic server code instead.
    answer = claims_text.strip()
    if not answer:
        answer = "我暂时没有找到可验证的资料。你可以补充设备名称、编号或更具体的问题。"
    safe_answer = redact_text(answer).text
    valid_memory_ids = list(
        dict.fromkeys(int(value) for value in draft.used_memory_ids if value > 0)
    )
    valid_l0_ids = list(
        dict.fromkeys(int(value) for value in draft.used_l0_message_ids if value > 0)
    )
    return safe_answer, list(citations.values()), valid_memory_ids, valid_l0_ids
