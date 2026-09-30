from __future__ import annotations

import json
from pathlib import Path

from quality_metrics import score_dataset

ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "qa_system" / "datasets"
THRESHOLDS = {
    "contextual_precision_at_k": 0.80,
    "contextual_recall": 0.80,
    "contextual_relevancy": 0.80,
    "faithfulness": 0.90,
    "answer_relevancy": 0.90,
    "factual_correctness": 0.90,
    "citation_validity": 1.0,
    "tenant_citation_isolation": 1.0,
}


def _read(name: str) -> list[dict[str, object]]:
    return json.loads((DATASETS / name).read_text(encoding="utf-8"))


def _evaluate(name: str) -> dict[str, float]:
    scores = score_dataset(_read(name))
    target = ROOT / "qa_system" / "results" / name.replace(".json", "-metrics.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"offline_fixture_only": True, "thresholds": THRESHOLDS, "scores": scores}, indent=2
        ),
        encoding="utf-8",
    )
    return scores


def test_golden_offline_cassette_scores_meet_rag_targets() -> None:
    scores = _evaluate("golden.json")
    assert all(scores[key] >= threshold for key, threshold in THRESHOLDS.items()), scores


def test_holdout_offline_cassette_scores_meet_rag_targets() -> None:
    scores = _evaluate("holdout.json")
    assert all(scores[key] >= threshold for key, threshold in THRESHOLDS.items()), scores


def test_holdout_ids_and_questions_do_not_overlap_golden() -> None:
    golden = _read("golden.json")
    holdout = _read("holdout.json")
    assert {case["id"] for case in golden}.isdisjoint({case["id"] for case in holdout})
    assert {case["question"] for case in golden}.isdisjoint({case["question"] for case in holdout})
