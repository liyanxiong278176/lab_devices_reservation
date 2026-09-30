from app.ai.dlp import redact_text, redact_value


def test_redacts_credentials_and_direct_identifiers() -> None:
    original = (
        "联系 alice@example.edu 或 13812345678，身份证 11010519491231002X；"
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789"
    )

    result = redact_text(original)

    assert "alice@example.edu" not in result.text
    assert "13812345678" not in result.text
    assert "11010519491231002X" not in result.text
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in result.text
    assert set(result.categories) == {"credential", "email", "identity_number", "phone"}


def test_redacts_password_assignments_and_nested_sensitive_fields() -> None:
    result = redact_text("password='correct horse battery staple' api_key=sk-abcdefghijklmno")
    structured, categories = redact_value(
        {
            "phone": "13812345678",
            "description": "请联系 alice@example.edu",
            "reservation_id": 12,
        }
    )

    assert "correct horse battery staple" not in result.text
    assert "sk-abcdefghijklmno" not in result.text
    assert "sensitive_field" in categories
    assert "alice@example.edu" not in structured["description"]
    assert structured["phone"] == "[已脱敏]"
    assert structured["reservation_id"] == 12


def test_leaves_ordinary_chinese_and_natural_dates_unchanged() -> None:
    text = "请预约设备 12，使用日期为 2026 年 10 月 3 日。"

    assert redact_text(text).text == text
