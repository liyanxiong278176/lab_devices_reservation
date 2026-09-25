import pytest
from app.core.errors import ApiError
from app.infrastructure.db.pagination import MAX_PAGE_SKIP, page_metadata, page_offset


def test_page_offset_allows_the_boundary_and_rejects_beyond_it() -> None:
    page_size = 20
    last_reachable_page = MAX_PAGE_SKIP // page_size + 1

    assert page_offset(last_reachable_page, page_size) == MAX_PAGE_SKIP
    with pytest.raises(ApiError) as error:
        page_offset(last_reachable_page + 1, page_size)

    assert error.value.status_code == 422
    assert error.value.code == "PAGE_DEPTH_EXCEEDED"
    assert "100,000" in error.value.message


def test_page_metadata_caps_page_count_but_keeps_truncation_visible() -> None:
    assert page_metadata(total=100_001, page_size=20) == (5_001, False)
    assert page_metadata(total=100_021, page_size=20) == (5_001, True)
    assert page_metadata(total=0, page_size=20) == (0, False)
