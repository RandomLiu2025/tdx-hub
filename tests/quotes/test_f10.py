from __future__ import annotations

import pytest

from tdxhub.exceptions import TdxhubValidationException
from tdxhub.f10 import F10_COLUMNS, normalize_f10_content
from tdxhub.quotes import StdQuotes


class _F10Client:
    def __init__(self, categories=None, contents=None):
        self.categories = categories or []
        self.contents = contents or {}
        self.category_calls = []
        self.content_calls = []

    def get_company_info_category(self, market, code):
        self.category_calls.append((market, code))
        return self.categories

    def get_company_info_content(self, **kwargs):
        self.content_calls.append(kwargs)
        return self.contents[(kwargs["filename"], kwargs["start"], kwargs["length"])]


def _quotes(client):
    quotes = object.__new__(StdQuotes)
    quotes.client = client
    return quotes


def _categories():
    return [
        {"name": "最新提示", "filename": "000001.txt", "start": 0, "length": 12},
        {"name": "公司概况", "filename": "000001.txt", "start": 12, "length": 24},
    ]


def test_normalize_f10_content_preserves_indentation_and_cleans_layout():
    raw = "\r\n标题   \r\n  项目一\t \r项目二\r\n\r\n\r\n结尾  \r\n"

    assert normalize_f10_content(raw) == "标题\n  项目一\n项目二\n\n结尾"
    assert normalize_f10_content(None) == ""


def test_f10_returns_fixed_schema_and_preserves_category_order():
    categories = _categories()
    client = _F10Client(
        categories,
        {
            ("000001.txt", 0, 12): "最新提示  \r\n正文",
            ("000001.txt", 12, 24): "公司概况\r\n  内容",
        },
    )

    result = _quotes(client).F10("SZ.000001")

    assert result.columns.tolist() == list(F10_COLUMNS)
    assert result["section"].tolist() == ["最新提示", "公司概况"]
    assert result[["full_code", "exchange", "market_id", "code"]].to_dict("records") == [
        {"full_code": "sz000001", "exchange": "sz", "market_id": 0, "code": "000001"},
        {"full_code": "sz000001", "exchange": "sz", "market_id": 0, "code": "000001"},
    ]
    assert result["content"].tolist() == ["最新提示\n正文", "公司概况\n  内容"]
    assert client.category_calls == [(0, "000001")]
    assert [call["start"] for call in client.content_calls] == [0, 12]


def test_f10_filters_trimmed_section_without_reading_other_sections():
    client = _F10Client(
        _categories(),
        {("000001.txt", 12, 24): "公司概况"},
    )

    result = _quotes(client).F10("000001", name="  公司概况  ")

    assert result["section"].tolist() == ["公司概况"]
    assert client.content_calls == [
        {
            "market": 0,
            "code": "000001",
            "filename": "000001.txt",
            "start": 12,
            "length": 24,
        }
    ]


@pytest.mark.parametrize("categories, name", [([], ""), (_categories(), "不存在")])
def test_f10_returns_fixed_empty_frame_without_content_requests(categories, name):
    client = _F10Client(categories)

    result = _quotes(client).F10("sh600519", name=name)

    assert result.empty
    assert result.columns.tolist() == list(F10_COLUMNS)
    assert client.content_calls == []


def test_f10_rejects_non_string_section_name_before_network_request():
    client = _F10Client(_categories())

    with pytest.raises(TdxhubValidationException, match="name 必须是字符串"):
        _quotes(client).F10("000001", name=None)

    assert client.category_calls == []
