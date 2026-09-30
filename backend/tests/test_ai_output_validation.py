from app.ai.output_validation import AnswerDraft, EvidenceClaim, validate_answer_draft


def test_keeps_only_exactly_supported_cited_claims() -> None:
    source = {
        "point_id": "doc-chunk-1",
        "title": "离心机说明",
        "content": "使用前检查转子是否有裂纹，并确认盖锁正常。",
    }
    draft = AnswerDraft(
        claims=[
            EvidenceClaim(
                text="检查转子是否有裂纹",
                source_ids=["doc-chunk-1"],
                evidence_quote="使用前检查转子是否有裂纹，并确认盖锁正常。",
            ),
            EvidenceClaim(
                text="设备必须每年校准",
                source_ids=["doc-chunk-1"],
                evidence_quote="设备必须每年校准",
            ),
            EvidenceClaim(
                text="检查转子是否有裂纹",
                source_ids=["made-up-id"],
                evidence_quote="使用前检查转子是否有裂纹，并确认盖锁正常。",
            ),
        ]
    )

    answer, citations, memory_ids, l0_ids = validate_answer_draft(draft, [source])

    assert "检查转子是否有裂纹" in answer
    assert "设备必须每年校准" not in answer
    assert answer.count("[citation:doc-chunk-1]") == 1
    assert citations == [source]
    assert memory_ids == []
    assert l0_ids == []


def test_redacts_answer_and_drops_non_evidence_claims() -> None:
    draft = AnswerDraft(
        introduction="联系 alice@example.edu",
        claims=[
            EvidenceClaim(
                text="原文不存在的信息",
                source_ids=["source-1"],
                evidence_quote="别的内容",
            )
        ],
        used_memory_ids=[4, 4, -1],
        used_l0_message_ids=[8, 8, -1],
    )

    answer, citations, memory_ids, l0_ids = validate_answer_draft(
        draft,
        [{"point_id": "source-1", "content": "别的内容"}],
    )

    assert "alice@example.edu" not in answer
    assert answer.startswith("我暂时没有找到可验证的资料")
    assert citations == []
    assert memory_ids == [4]
    assert l0_ids == [8]


def test_parent_section_evidence_can_support_claim_but_keeps_child_source_id() -> None:
    source = {
        "point_id": "child-17",
        "content": "运行后等待转子完全停止。",
        "context_content": "## 离心机安全\n使用前检查转子。运行后等待转子完全停止。再打开舱盖。",
    }
    answer, citations, _, _ = validate_answer_draft(
        AnswerDraft(
            claims=[
                EvidenceClaim(
                    text="再打开舱盖",
                    source_ids=["child-17"],
                    evidence_quote="再打开舱盖",
                )
            ]
        ),
        [source],
    )

    assert "再打开舱盖 [citation:child-17]" in answer
    assert citations == [source]


def test_drops_claim_that_omits_negation_from_cited_evidence() -> None:
    evidence = "The device is not available for reservation."
    answer, citations, _, _ = validate_answer_draft(
        AnswerDraft(
            claims=[
                EvidenceClaim(
                    text="available for reservation",
                    source_ids=["device-status"],
                    evidence_quote=evidence,
                )
            ]
        ),
        [{"point_id": "device-status", "content": evidence}],
    )

    assert "available for reservation" not in answer
    assert citations == []


def test_drops_claim_that_omits_uncertainty_from_cited_evidence() -> None:
    evidence = "The device may be available for reservation."
    answer, citations, _, _ = validate_answer_draft(
        AnswerDraft(
            claims=[
                EvidenceClaim(
                    text="available for reservation",
                    source_ids=["device-status"],
                    evidence_quote=evidence,
                )
            ]
        ),
        [{"point_id": "device-status", "content": evidence}],
    )

    assert "available for reservation" not in answer
    assert citations == []
