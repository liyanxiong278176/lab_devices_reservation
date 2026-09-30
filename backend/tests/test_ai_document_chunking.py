from app.ai.rag.qdrant_store import split_document_sections


def test_markdown_chunking_preserves_heading_tree_and_parent_links() -> None:
    text = """# 实验室安全
总则内容。

## 离心机
使用前检查转子。运行后等待转子停止。

### 异常处理
发现裂纹时立即停机并报修。
"""

    sections, chunks = split_document_sections(text, chunk_size=18, overlap=3)

    assert [(item.heading, item.parent_index, item.section_path) for item in sections] == [
        ("实验室安全", None, "实验室安全"),
        ("离心机", 0, "实验室安全 / 离心机"),
        ("异常处理", 1, "实验室安全 / 离心机 / 异常处理"),
    ]
    assert chunks
    assert all(chunk.content for chunk in chunks)
    assert all(chunk.section_index in {0, 1, 2} for chunk in chunks)
    assert any(chunk.section_path.endswith("离心机") for chunk in chunks)
    assert any(chunk.section_path.endswith("异常处理") for chunk in chunks)


def test_unstructured_document_uses_recursive_separator_fallback() -> None:
    text = "第一段。第二段！第三段？" * 30

    sections, chunks = split_document_sections(text, chunk_size=24, overlap=4)

    assert len(sections) == 1
    assert sections[0].section_path == "全文"
    assert len(chunks) > 1
    assert all(len(chunk.content) <= 26 for chunk in chunks)
