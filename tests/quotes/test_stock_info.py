from __future__ import annotations

import pandas as pd
import pytest

from tdxhub.exceptions import TdxhubValidationException
from tdxhub.quotes import StdQuotes
from tdxhub.stock_info import STOCK_INFO_COLUMNS


def _client() -> StdQuotes:
    return object.__new__(StdQuotes)


def test_stock_info_empty_input_returns_fixed_schema_without_fetching(monkeypatch):
    quotes = _client()
    monkeypatch.setattr(quotes, "stocks", lambda *_args, **_kwargs: pytest.fail("unexpected fetch"))

    result = quotes.stock_info([])

    assert result.empty
    assert result.columns.tolist() == STOCK_INFO_COLUMNS
    assert len(result.columns) == 37
    assert not {"security", "quote", "finance"} & set(result.columns)


@pytest.mark.parametrize("symbols", [None, 123, "", "bad-code", ["600519", 1]])
def test_stock_info_rejects_invalid_symbols(symbols):
    with pytest.raises(TdxhubValidationException, match="证券代码"):
        _client().stock_info(symbols)


def test_stock_info_rejects_non_boolean_refresh():
    with pytest.raises(TdxhubValidationException, match="refresh_industries"):
        _client().stock_info("600519", refresh_industries="yes")


def test_stock_info_merges_sources_calculates_fields_and_restores_input_order(monkeypatch):
    quotes = _client()
    calls: list[tuple] = []

    directories = {
        0: pd.DataFrame([
            {"code": "000001", "name": "平安银行", "decimal_point": 2},
        ]),
        1: pd.DataFrame([
            {"code": "600519", "name": "贵州茅台", "decimal_point": 2},
        ]),
        2: pd.DataFrame([
            {"market": "bj", "code": "920001", "name": "北交样本", "security_type": "stock"},
        ]),
    }

    def stocks(market):
        calls.append(("stocks", market))
        return directories[market]

    def realtime(symbol):
        calls.append(("quotes", symbol))
        return pd.DataFrame([
            {
                "market": 1,
                "code": "600519",
                "price": 20.0,
                "last_close": 16.0,
                "open": 17.0,
                "high": 21.0,
                "low": 15.0,
                "vol": 1_000.0,
                "amount": 1_900_000.0,
            },
            {
                "market": 0,
                "code": "000001",
                "price": 10.0,
                "last_close": 0.0,
                "open": 9.0,
                "high": 11.0,
                "low": 8.0,
                "vol": 500.0,
                "amount": 500_000.0,
            },
            {
                "market": 2, "code": "920001", "price": 17.85,
                "last_close": 17.0, "vol": 1_000.0, "amount": 1_785_000.0,
            },
        ])

    def industries(symbols, *, refresh):
        calls.append(("stock_industries", symbols, refresh))
        return pd.DataFrame([
            {
                "market": "sh",
                "code": "600519",
                "tdx_industry_code": "T0501",
                "tdx_industry_name": "白酒",
                "tdx_industry_source": "tdx",
                "sw_industry_code": "X080301",
                "sw_industry_name": "白酒Ⅲ",
                "sw_industry_source": "sw",
                "sw_level1_code": "X08",
                "sw_level1_name": "食品饮料",
                "sw_level2_code": "X0803",
                "sw_level2_name": "白酒Ⅱ",
                "sw_level3_code": "X080301",
                "sw_level3_name": "白酒Ⅲ",
            }
        ])

    def finance(symbol):
        calls.append(("finance", symbol))
        if symbol == "sh600519":
            return pd.DataFrame([{
                "code": "600519",
                "liutongguben": 70_000_000,
                "zongguben": 80_000_000,
                "ipo_date": 20010827,
                "updated_date": 20260630,
                "jinglirun": 1.0,
            }])
        if symbol == "bj920001":
            return pd.DataFrame([{
                "code": "920001", "liutongguben": 8_000_000,
                "zongguben": 10_000_000, "ipo_date": 20230101,
                "updated_date": 20260630,
            }])
        return pd.DataFrame([{
            "code": "000001",
            "liutongguben": 5_000_000,
            "zongguben": 6_000_000,
            "ipo_date": "19910403",
            "updated_date": "2026-03-31",
        }])

    def xdxr(symbol):
        calls.append(("xdxr", symbol))
        if symbol != "sh600519":
            return pd.DataFrame()
        frame = pd.DataFrame([{
            "date": "2026-01-01",
            "category": 5,
            "code": "600519",
            "panhouliutong": 1_000,
            "houzongguben": 2_000,
        }])
        frame.attrs["equity_unit"] = "ten_thousand_shares"
        return frame

    def auction(symbol):
        calls.append(("call_auction", symbol))
        if symbol == "sh600519":
            return pd.DataFrame([
                {"price": 16.5, "matched": 100},
                {"price": 17.0, "matched": 200},
            ])
        return pd.DataFrame()

    monkeypatch.setattr(quotes, "stocks", stocks)
    monkeypatch.setattr(quotes, "quotes", realtime)
    monkeypatch.setattr(quotes, "stock_industries", industries)
    monkeypatch.setattr(quotes, "finance", finance)
    monkeypatch.setattr(quotes, "xdxr", xdxr)
    monkeypatch.setattr(quotes, "call_auction", auction)

    result = quotes.stock_info(
        ["SH.600519", "sz000001", "bj920001", "600519"],
        refresh_industries=True,
    )

    assert result.columns.tolist() == STOCK_INFO_COLUMNS
    assert result["full_code"].tolist() == ["sh600519", "sz000001", "bj920001", "sh600519"]
    assert calls.count(("quotes", ["sh600519", "sz000001", "bj920001"])) == 1
    assert calls.count(("finance", "sh600519")) == 1
    assert calls.count(("xdxr", "sh600519")) == 1
    assert calls.count(("finance", "bj920001")) == 1
    assert calls.count(("xdxr", "bj920001")) == 1
    assert ("call_auction", "bj920001") not in calls
    assert result.attrs["skipped_sources"] == {"bj920001": ["call_auction"]}

    sh = result.iloc[0]
    assert sh["exchange"] == "sh"
    assert sh["market_id"] == 1
    assert sh["name"] == "贵州茅台"
    assert sh["category"] == "a_share"
    assert sh["board"] == "主板"
    assert sh["change"] == pytest.approx(4.0)
    assert sh["change_pct"] == pytest.approx(25.0)
    assert sh["volume_hand"] == pytest.approx(1_000.0)
    assert sh["open_amount_yuan"] == pytest.approx(340_000.0)
    assert sh["circulating_shares"] == 10_000_000
    assert sh["total_shares"] == 20_000_000
    assert sh["turnover_rate"] == pytest.approx(1.0)
    assert sh["circulating_market_value"] == pytest.approx(200_000_000.0)
    assert sh["total_market_value"] == pytest.approx(400_000_000.0)
    assert sh["eps"] is None
    assert sh["ipo_date"] == "2001-08-27"
    assert sh["updated_date"] == "2026-06-30"
    assert sh["sw_level1_name"] == "食品饮料"

    sz = result.iloc[1]
    assert sz["circulating_shares"] == 5_000_000
    assert sz["total_shares"] == 6_000_000
    assert sz["change"] == pytest.approx(10.0)
    assert sz["change_pct"] is None
    assert sz["open_amount_yuan"] is None

    bj = result.iloc[2]
    assert bj["category"] == "a_share"
    assert bj["board"] == "北交所"
    assert bj["last_price"] == pytest.approx(17.85)
    assert bj["circulating_shares"] == 8_000_000
    assert bj["total_shares"] == 10_000_000
    assert bj["turnover_rate"] == pytest.approx(1.25)
    assert bj["total_market_value"] == pytest.approx(178_500_000)
    assert bj["ipo_date"] == "2023-01-01"
    assert bj["updated_date"] == "2026-06-30"
    assert bj["open_amount_yuan"] is None


def test_stock_info_maps_category_and_board_without_optional_data(monkeypatch):
    quotes = _client()
    directories = {
        0: pd.DataFrame([
            {"code": "300750", "name": "宁德时代"},
            {"code": "159915", "name": "创业板ETF"},
        ]),
        1: pd.DataFrame([
            {"code": "688981", "name": "中芯国际"},
            {"code": "000001", "name": "上证指数"},
        ]),
    }
    monkeypatch.setattr(quotes, "stocks", lambda market: directories[market])
    monkeypatch.setattr(quotes, "quotes", lambda _symbols: pd.DataFrame())
    monkeypatch.setattr(quotes, "stock_industries", lambda _symbols, refresh=False: pd.DataFrame())
    monkeypatch.setattr(quotes, "finance", lambda _symbol: pd.DataFrame())
    monkeypatch.setattr(quotes, "xdxr", lambda _symbol: pd.DataFrame())
    monkeypatch.setattr(quotes, "call_auction", lambda _symbol: pd.DataFrame())

    result = quotes.stock_info(["300750", "159915", "sh688981", "sh000001"])

    assert result[["category", "board"]].to_dict("records") == [
        {"category": "a_share", "board": "创业板"},
        {"category": "etf", "board": None},
        {"category": "a_share", "board": "科创板"},
        {"category": "index", "board": None},
    ]


def test_stock_info_preserves_explicit_eps_and_adds_context_to_source_errors(monkeypatch):
    quotes = _client()
    monkeypatch.setattr(
        quotes,
        "stocks",
        lambda _market: pd.DataFrame([{"code": "600519", "name": "贵州茅台"}]),
    )
    monkeypatch.setattr(
        quotes,
        "quotes",
        lambda _symbols: pd.DataFrame([{"market": 1, "code": "600519", "price": 20.0}]),
    )
    monkeypatch.setattr(quotes, "stock_industries", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(quotes, "xdxr", lambda _symbol: pd.DataFrame())
    monkeypatch.setattr(quotes, "call_auction", lambda _symbol: pd.DataFrame())
    monkeypatch.setattr(quotes, "finance", lambda _symbol: pd.DataFrame([{"eps": 3.25}]))

    result = quotes.stock_info("sh600519")

    assert result.iloc[0]["eps"] == pytest.approx(3.25)

    def failed_finance(_symbol):
        raise RuntimeError("finance unavailable")

    monkeypatch.setattr(quotes, "finance", failed_finance)
    with pytest.raises(RuntimeError, match="finance unavailable") as captured:
        quotes.stock_info("sh600519")

    assert "汇总证券 sh600519 数据失败" in getattr(captured.value, "__notes__", [])


def _stub_stock_info_dependencies(monkeypatch, quotes, *, stocks=None):
    monkeypatch.setattr(
        quotes,
        "stocks",
        stocks or (lambda _market: pd.DataFrame([{"code": "600519", "name": "贵州茅台"}])),
    )
    monkeypatch.setattr(quotes, "quotes", lambda _symbols: pd.DataFrame())
    monkeypatch.setattr(quotes, "stock_industries", lambda *_args, **_kwargs: pd.DataFrame())


def test_stock_info_runs_independent_sources_concurrently(monkeypatch):
    import threading

    quotes = _client()
    _stub_stock_info_dependencies(monkeypatch, quotes)
    barrier = threading.Barrier(3)
    threads = set()
    lock = threading.Lock()

    def source(_symbol):
        with lock:
            threads.add(threading.get_ident())
        barrier.wait(timeout=2)
        return pd.DataFrame()

    monkeypatch.setattr(quotes, "finance", source)
    monkeypatch.setattr(quotes, "xdxr", source)
    monkeypatch.setattr(quotes, "call_auction", source)

    result = quotes.stock_info("sh600519", max_workers=3)

    assert result["full_code"].tolist() == ["sh600519"]
    assert len(threads) == 3


@pytest.mark.parametrize("max_workers", [True, 0, 17, 1.5, "4"])
def test_stock_info_rejects_invalid_max_workers(max_workers):
    with pytest.raises(TdxhubValidationException, match="max_workers"):
        _client().stock_info("sh600519", max_workers=max_workers)


def test_stock_info_rejects_non_boolean_directory_refresh():
    with pytest.raises(TdxhubValidationException, match="refresh_directories"):
        _client().stock_info("sh600519", refresh_directories="yes")


def test_stock_info_delegates_directory_cache_and_explicit_refresh(monkeypatch):
    quotes = _client()
    directory_calls = 0

    refresh_calls = []

    def stocks(_market, *, refresh=False):
        nonlocal directory_calls
        directory_calls += 1
        refresh_calls.append(refresh)
        return pd.DataFrame([{"code": "600519", "name": f"贵州茅台-{directory_calls}"}])

    _stub_stock_info_dependencies(monkeypatch, quotes, stocks=stocks)
    monkeypatch.setattr(quotes, "finance", lambda _symbol: pd.DataFrame())
    monkeypatch.setattr(quotes, "xdxr", lambda _symbol: pd.DataFrame())
    monkeypatch.setattr(quotes, "call_auction", lambda _symbol: pd.DataFrame())

    first = quotes.stock_info("sh600519")
    second = quotes.stock_info("sh600519")
    refreshed = quotes.stock_info("sh600519", refresh_directories=True)

    assert directory_calls == 3
    assert refresh_calls == [False, False, True]
    assert first.iloc[0]["name"] == "贵州茅台-1"
    assert second.iloc[0]["name"] == "贵州茅台-2"
    assert refreshed.iloc[0]["name"] == "贵州茅台-3"


class BoundPoolClient:
    def __init__(self, created):
        self.created = created
        self.closed = False
        self.created.append(self)

    def fork(self):
        return BoundPoolClient(self.created)

    def close(self):
        self.closed = True


def test_stock_info_binds_distinct_pooled_clients_to_workers(monkeypatch):
    import threading

    from tdxhub.failover import FailoverClientPool

    quotes = _client()
    created = []
    quotes.client = BoundPoolClient(created)
    quotes._stock_info_client_pool = FailoverClientPool(quotes.client, max_size=3)
    _stub_stock_info_dependencies(monkeypatch, quotes)
    barrier = threading.Barrier(3)
    seen_clients = []
    lock = threading.Lock()

    def source(_symbol):
        with lock:
            seen_clients.append(quotes.client)
        barrier.wait(timeout=2)
        return pd.DataFrame()

    monkeypatch.setattr(quotes, "finance", source)
    monkeypatch.setattr(quotes, "xdxr", source)
    monkeypatch.setattr(quotes, "call_auction", source)

    result = quotes.stock_info("sh600519", max_workers=3)

    assert result["full_code"].tolist() == ["sh600519"]
    assert len(created) == 3
    assert len({id(client) for client in seen_clients}) == 3
    assert quotes.client is created[0]
    quotes.close()
    assert all(client.closed for client in created)


def test_beijing_stock_info_keeps_fractional_xdxr_equity_precision(monkeypatch):
    quotes = _client()
    _stub_stock_info_dependencies(
        monkeypatch, quotes,
        stocks=lambda _market: pd.DataFrame([{"code": "920026", "name": "卓兆点胶"}]),
    )
    monkeypatch.setattr(quotes, "quotes", lambda _symbols: pd.DataFrame([{
        "market": 2, "code": "920026", "price": 17.85, "vol": 10_563,
    }]))
    actions = pd.DataFrame([{
        "date": "2026-06-10", "category": 9,
        "panhouliutong": 8662.2138671875, "houzongguben": 11490.814453125,
    }])
    actions.attrs["equity_unit"] = "ten_thousand_shares"
    monkeypatch.setattr(quotes, "xdxr", lambda _symbol: actions)
    monkeypatch.setattr(quotes, "finance", lambda _symbol: pd.DataFrame([{
        "zongguben": 114908095.703125, "liutongguben": 86622099.609375,
    }]))
    monkeypatch.setattr(quotes, "call_auction", lambda _symbol: pytest.fail("BJ auction is unverified"))

    row = quotes.stock_info("bj920026").iloc[0]

    # Latest XDXR takes precedence over finance; convert 万股 to 股 before int.
    assert row["circulating_shares"] == 86_622_138
    assert row["total_shares"] == 114_908_144
    assert row["circulating_market_value"] == pytest.approx(17.85 * 86_622_138)
    assert row["total_market_value"] == pytest.approx(17.85 * 114_908_144)
    assert row["turnover_rate"] == pytest.approx(10_563 * 100 / 86_622_138 * 100)
    assert pd.isna(row["open_amount_yuan"])
    assert actions.iloc[0]["panhouliutong"] == 8662.2138671875
