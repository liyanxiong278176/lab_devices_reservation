"""Deterministic, reviewable RAG quality metrics for offline cassette outputs."""

from __future__ import annotations

from typing import Any


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def score_case(case: dict[str, Any], *, k: int = 3) -> dict[str, float]:
    contexts = case.get("contexts", [])
    expected_ids = set(map(str, case.get("expected_points", [])))
    retrieved_ids = [str(context.get("point_id")) for context in contexts[:k]]
    relevant_ids = [point_id for point_id in retrieved_ids if point_id in expected_ids]
    facts = [str(fact).casefold() for fact in case.get("expected_facts", [])]
    answer = str(case.get("answer", "")).casefold()
    context_text = " ".join(str(context.get("content", "")) for context in contexts).casefold()
    answer_facts = sum(fact in answer for fact in facts)
    supported_facts = sum(fact in answer and fact in context_text for fact in facts)
    citations = set(map(str, case.get("citations", [])))
    authorized_context_ids = {
        str(context.get("point_id"))
        for context in contexts
        if context.get("college") in {case.get("tenant"), "public"}
    }
    citation_validity = _ratio(len(citations & authorized_context_ids), len(citations))
    return {
        "contextual_precision_at_k": _ratio(len(relevant_ids), min(k, len(retrieved_ids))),
        "contextual_recall": _ratio(len(set(relevant_ids)), len(expected_ids)),
        "contextual_relevancy": _ratio(sum(fact in context_text for fact in facts), len(facts)),
        "faithfulness": _ratio(supported_facts, answer_facts),
        "answer_relevancy": _ratio(answer_facts, len(facts)),
        "factual_correctness": _ratio(supported_facts, len(facts)),
        "citation_validity": citation_validity,
        "tenant_citation_isolation": citation_validity,
    }


def score_dataset(cases: list[dict[str, Any]]) -> dict[str, float]:
    if not cases:
        raise ValueError("dataset must contain at least one case")
    measurements = [score_case(case) for case in cases]
    return {
        key: round(sum(result[key] for result in measurements) / len(measurements), 4)
        for key in measurements[0]
    }
