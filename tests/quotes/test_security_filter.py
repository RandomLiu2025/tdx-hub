from __future__ import annotations

import pandas as pd
import pytest

from tdxhub.exceptions import TdxhubValidationException
from tdxhub.quotes import StdQuotes
from tdxhub.security import classify_security, filter_security_directory, normalize_security_type


@pytest.mark.parametrize(
    ("market", "code", "name", "expected"),
    [
        (0, "000001", "平安银行", "a_stock"),
        (0, "300750", "宁德时代", "a_stock"),
        (0, "200002", "万科B", "b_stock"),
        (0, "399001", "深证成指", "index"),
        (0, "159915", "创业板ETF", "etf"),
        (0, "160105", "南方积极配置", "fund"),
        (0, "123001", "蓝标转债", "bond"),
        (0, "777777", "未知证券", "other"),
        (1, "600519", "贵州茅台", "a_stock"),
        (1, "688981", "中芯国际", "a_stock"),
        (1, "900901", "云赛B股", "b_stock"),
        (1, "000001", "上证指数", "index"),
        (1, "510300", "沪深300ETF", "etf"),
        (1, "588000", "科创50ETF", "etf"),
        (1, "501018", "南方原油", "fund"),
        (1, "110059", "浦发转债", "bond"),
        (1, "777777", "未知证券", "other"),
        (2, "430047", "诺思兰德", "a_stock"),
        (2, "899050", "北证50", "index"),
    ],
)
def test_classify_security_by_market_code_and_name(market, code, name, expected):
    assert classify_security(market, code, name) == expected


def test_etf_name_fallback_takes_precedence_over_fund_and_bond_ranges():
    assert classify_security(1, "501999", "测试ETF") == "etf"
    assert classify_security(1, "110999", "债券ETF") == "etf"


def test_normalize_security_type_ignores_case_and_whitespace_and_rejects_unknown_values():
    assert normalize_security_type(None) is None
    assert normalize_security_type("  ETF ") == "etf"
    assert normalize_security_type("A_STOCK") == "a_stock"

    with pytest.raises(TdxhubValidationException, match="security_type"):
        normalize_security_type("stock")
    with pytest.raises(TdxhubValidationException, match="security_type"):
        normalize_security_type(1)


def test_filter_security_directory_preserves_schema_order_attrs_and_resets_index():
    directory = pd.DataFrame(
        [
            {"code": "510300", "name": "沪深300ETF", "decimal_point": 3},
            {"code": "600519", "name": "贵州茅台", "decimal_point": 2},
            {"code": "588000", "name": "科创50ETF", "decimal_point": 3},
        ],
        index=[4, 8, 9],
    )
    directory.attrs["source"] = "test"

    unchanged = filter_security_directory(directory, market=1, security_type=None)
    filtered = filter_security_directory(directory, market=1, security_type=" ETF ")

    assert unchanged is directory
    assert filtered.to_dict("records") == [
        {"code": "510300", "name": "沪深300ETF", "decimal_point": 3},
        {"code": "588000", "name": "科创50ETF", "decimal_point": 3},
    ]
    assert filtered.columns.tolist() == directory.columns.tolist()
    assert filtered.index.tolist() == [0, 1]
    assert filtered.attrs == {"source": "test"}


@pytest.fixture(autouse=True)
def _isolate_quote_metadata_cache(tmp_path, monkeypatch):
    from tdxhub.quotes import _QUOTE_METADATA_CACHE

    monkeypatch.setattr('tdxhub.quotes._quote_metadata_cache_directory', lambda: tmp_path)
    _QUOTE_METADATA_CACHE.clear_memory()
    yield
    _QUOTE_METADATA_CACHE.clear_memory()


class _DirectoryClient:
    def __init__(self):
        self.calls = []

    def get_security_count(self, market):
        self.calls.append(("count", market))
        return 4

    def get_security_list(self, market, start):
        self.calls.append(("list", market, start))
        return [
            {"code": "600519", "name": "贵州茅台"},
            {"code": "000001", "name": "上证指数"},
            {"code": "510300", "name": "沪深300ETF"},
            {"code": "110059", "name": "浦发转债"},
        ]


def test_stocks_supports_generic_filter_without_changing_default_directory():
    quotes = object.__new__(StdQuotes)
    quotes.client = _DirectoryClient()

    default = quotes.stocks(1)
    etfs = quotes.stocks(1, security_type="etf")

    assert default["code"].tolist() == ["600519", "000001", "510300", "110059"]
    assert etfs["code"].tolist() == ["510300"]
    assert etfs.index.tolist() == [0]
    assert quotes.client.calls == [
        ("count", 1),
        ("list", 1, 0),
    ]


def test_stocks_cache_is_global_persistent_and_explicitly_refreshable():
    from tdxhub.quotes import _QUOTE_METADATA_CACHE, _quote_metadata_cache_file

    first = object.__new__(StdQuotes)
    first.client = _DirectoryClient()
    second = object.__new__(StdQuotes)
    second.client = _DirectoryClient()

    original = first.stocks(1)
    shared = second.stocks(1)
    _QUOTE_METADATA_CACHE.clear_memory()
    persisted = second.stocks(1)
    refreshed = second.stocks(1, refresh=True)

    pd.testing.assert_frame_equal(original, shared)
    pd.testing.assert_frame_equal(original, persisted)
    pd.testing.assert_frame_equal(original, refreshed)
    assert first.client.calls == [("count", 1), ("list", 1, 0)]
    assert second.client.calls == [("count", 1), ("list", 1, 0)]
    assert _quote_metadata_cache_file("stocks-1").is_file()


def test_stock_count_keeps_fast_unfiltered_path_and_filters_full_directory():
    quotes = object.__new__(StdQuotes)
    quotes.client = _DirectoryClient()

    assert quotes.stock_count(1) == 4
    assert quotes.client.calls == [("count", 1)]

    quotes.client.calls.clear()
    assert quotes.stock_count(1, security_type="index") == 1
    assert quotes.client.calls == [("count", 1), ("list", 1, 0)]


def test_stock_all_forwards_normalized_filter_to_all_markets(monkeypatch):
    quotes = object.__new__(StdQuotes)
    calls = []

    def stocks(market, security_type=None):
        calls.append((market, security_type))
        return pd.DataFrame({"market": [market], "code": [f"{market:06d}"]})

    monkeypatch.setattr(quotes, "stocks", stocks)

    result = quotes.stock_all(security_type=" ETF ")

    assert calls == [(0, "etf"), (1, "etf"), (2, "etf")]
    assert result["market"].tolist() == [0, 1, 2]


def test_stocks_rejects_non_boolean_refresh():
    quotes = object.__new__(StdQuotes)

    with pytest.raises(TdxhubValidationException, match="refresh"):
        quotes.stocks(1, refresh="yes")


def test_stocks_uses_separate_cache_entry_for_each_market():
    from tdxhub.quotes import _quote_metadata_cache_file

    quotes = object.__new__(StdQuotes)
    quotes.client = _DirectoryClient()

    quotes.stocks(0)
    quotes.stocks(1)
    quotes.stocks(0)
    quotes.stocks(1)

    assert quotes.client.calls == [
        ("count", 0),
        ("list", 0, 0),
        ("count", 1),
        ("list", 1, 0),
    ]
    assert _quote_metadata_cache_file("stocks-0").is_file()
    assert _quote_metadata_cache_file("stocks-1").is_file()
