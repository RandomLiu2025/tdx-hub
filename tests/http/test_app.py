import pandas as pd
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from tdxhub.http.app import create_app  # noqa: E402
from tdxhub.http.service import MarketDataService  # noqa: E402


class FakeQuotes:
    def stock_count(self, market):
        return 8 + market

    def stocks(self, market):
        return pd.DataFrame([{"market": market, "code": "600519"}])

    def stock_list(self, market, start):
        return pd.DataFrame([{"market": market, "start": start}])

    def quotes(self, symbol):
        if symbol == ["boom"]:
            raise ConnectionError("upstream unavailable")
        return pd.DataFrame([{"code": code, "price": 10.5} for code in symbol])

    def stock_info(self, symbols, *, refresh_industries=False):
        assert refresh_industries is True
        records = {
            "sh600519": {
                "full_code": "sh600519",
                "security": {"code": "600519", "name": "贵州茅台"},
                "quote": {"price": 20.0},
                "finance": {"ipo_date": "2001-08-27"},
            },
            "sz000001": {
                "full_code": "sz000001",
                "security": {"code": "000001", "name": "平安银行"},
                "quote": {"price": 10.0},
                "finance": None,
            },
        }
        return pd.DataFrame([records[symbol] for symbol in symbols])

    def bars(self, **kwargs):
        return pd.DataFrame([kwargs])

    def call_auction(self, symbol):
        return pd.DataFrame([{"code": symbol}])

    def minute(self, symbol):
        return pd.DataFrame([{"code": symbol}])

    def minutes(self, **kwargs):
        return pd.DataFrame([kwargs])

    def transaction(self, **kwargs):
        return pd.DataFrame([kwargs])

    def transactions(self, **kwargs):
        return pd.DataFrame([kwargs])

    def transaction_all(self, **kwargs):
        return pd.DataFrame([{"method": "transaction_all", **kwargs}])

    def transactions_all(self, **kwargs):
        return pd.DataFrame([{"method": "transactions_all", **kwargs}])

    def bars_all(self, **kwargs):
        return pd.DataFrame([{"method": "bars_all", **kwargs}])

    def minute_241(self, **kwargs):
        return pd.DataFrame([{"method": "minute_241", **kwargs}])

    def index_all(self, **kwargs):
        return pd.DataFrame([{"method": "index_all", **kwargs}])

    def capital_flow(self, **kwargs):
        return pd.DataFrame([{"method": "capital_flow", **kwargs}])

    def capital_flow_history(self, **kwargs):
        return pd.DataFrame([{"method": "capital_flow_history", **kwargs}])

    def sector_capital_flow(self, **kwargs):
        return pd.DataFrame([{"method": "sector_capital_flow", **kwargs}])

    @staticmethod
    def _named_result(name):
        return pd.DataFrame([{"method": name}])

    def xdxr(self, **kwargs):
        return self._named_result("xdxr")

    def finance(self, **kwargs):
        return self._named_result("finance")

    def F10C(self, **kwargs):  # noqa: N802
        return self._named_result("F10C")

    def company_content(self, **kwargs):
        return self._named_result("company_content")

    def statistics(self, symbols=None):
        return self._named_result("statistics")

    def money_flow(self):
        return self._named_result("money_flow")

    def xgsg(self):
        return self._named_result("xgsg")

    def index(self, **kwargs):
        return pd.DataFrame([{"method": "index", **kwargs}])


def client():
    return TestClient(create_app(MarketDataService(FakeQuotes())))


def test_health_ready_and_success_envelope():
    http = client()

    assert http.get("/").json() == {"code": 0, "msg": "ok", "data": {"status": "running"}}
    assert http.get("/ready").json() == {
        "code": 0,
        "msg": "ok",
        "data": {"status": "ready", "standard": True, "extendedEnabled": False},
    }
    assert http.get("/count", params={"exchange": "sh"}).json() == {"code": 0, "msg": "ok", "data": 9}


def test_parameter_errors_are_http_400_with_common_envelope():
    http = client()

    missing = http.get("/quote")
    invalid = http.get("/kline", params={"type": "bad", "code": "600519", "start": 0, "count": 10})
    negative = http.get("/trade", params={"code": "600519", "start": -1, "count": 10})

    assert missing.status_code == 400
    assert missing.json()["code"] == 1
    assert invalid.status_code == 400
    assert invalid.json()["code"] == 1
    assert negative.status_code == 400
    assert negative.json()["code"] == 1


def test_upstream_errors_keep_http_200_and_extended_routes_are_404_when_disabled():
    http = client()

    failed = http.get("/quote", params={"codes": "boom"})
    disabled = http.get("/ex/markets")

    assert failed.status_code == 200
    assert failed.json() == {"code": 1, "msg": "upstream unavailable", "data": None}
    assert disabled.status_code == 404
    assert disabled.json() == {"code": 1, "msg": "扩展行情未启用", "data": None}


def test_routes_map_query_parameters_and_serialize_dataframes():
    http = client()

    quote = http.get("/quote", params={"codes": "sz000001,sh600519"})
    kline = http.get(
        "/kline",
        params={"type": 9, "code": "600519", "start": 2, "count": 30},
    )

    assert quote.json()["data"] == [
        {"code": "sz000001", "price": 10.5},
        {"code": "sh600519", "price": 10.5},
    ]
    assert kline.json()["data"] == [
        {"symbol": "600519", "frequency": 9, "start": 2, "offset": 30}
    ]


def test_ready_returns_error_envelope_when_standard_quotes_are_missing():
    http = TestClient(create_app(MarketDataService(None)))

    response = http.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "code": 1,
        "msg": "标准行情连接未就绪",
        "data": None,
    }


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/quote", {"codes": "   "}),
        ("/call_auction", {"code": "   "}),
        ("/kline", {"type": 256, "code": "600519", "start": 0, "count": 1}),
        ("/kline", {"type": 9, "code": "600519", "start": 65536, "count": 1}),
        ("/ex/quote", {"market": 256, "code": "00700"}),
        ("/ex/instruments", {"start": 4294967296, "count": 1}),
    ],
)
def test_query_parameters_enforce_go_integer_bounds_and_non_empty_text(path, params):
    response = client().get(path, params=params)

    assert response.status_code == 400
    assert response.json()["code"] == 1


def test_finance_company_statistics_and_index_routes():
    http = client()

    cases = [
        ("/gbbq", {"code": "600519"}, "xdxr"),
        ("/finance", {"exchange": "sh", "code": "600519"}, "finance"),
        ("/company/category", {"exchange": "sz", "code": "000001"}, "F10C"),
        (
            "/company/content",
            {
                "exchange": "sh",
                "code": "600519",
                "filename": "600519.txt",
                "start": 10,
                "length": 20,
            },
            "company_content",
        ),
        ("/tdx/stat", {}, "statistics"),
        ("/tdx/stat2", {}, "money_flow"),
        ("/tdx/xgsg", {}, "xgsg"),
        (
            "/index",
            {"type": 9, "code": "000001", "start": 2, "count": 30},
            "index",
        ),
    ]

    for path, params, method in cases:
        response = http.get(path, params=params)
        assert response.status_code == 200
        assert response.json()["code"] == 0
        assert response.json()["data"][0]["method"] == method


def test_single_page_and_all_data_routes():
    http = client()

    cases = [
        ("/code", {"exchange": "bj", "start": 1000}, {"market": 2, "start": 1000}),
        ("/trade/all", {"code": "600519"}, {"method": "transaction_all", "symbol": "600519"}),
        (
            "/trade/history/day",
            {"date": "20260910", "code": "600519"},
            {"method": "transactions_all", "symbol": "600519", "date": "20260910"},
        ),
        (
            "/kline/all",
            {"type": 9, "code": "600519", "since": "20260101"},
            {"method": "bars_all", "symbol": "600519", "frequency": 9, "since": "20260101"},
        ),
        (
            "/index/all",
            {"type": 5, "code": "000001"},
            {"method": "index_all", "symbol": "000001", "frequency": 5, "since": None},
        ),
    ]

    for path, params, expected in cases:
        response = http.get(path, params=params)
        assert response.status_code == 200
        assert response.json()["data"] == [expected]


def test_minute_241_route_maps_parameters_and_validates_input():
    http = client()

    response = http.get(
        "/kline/minute/241",
        params={"code": "600519", "since": "20260910"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == [
        {"method": "minute_241", "symbol": "600519", "since": "20260910"},
    ]
    for params in ({}, {"code": "   "}, {"code": "600519", "since": "2026-09-10"}):
        invalid = http.get("/kline/minute/241", params=params)
        assert invalid.status_code == 400
        assert invalid.json()["code"] == 1


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/code", {"exchange": "sh", "start": 65536}),
        ("/trade/all", {"code": "   "}),
        ("/trade/history/day", {"date": "   ", "code": "600519"}),
        ("/kline/all", {"type": 256, "code": "600519"}),
        ("/kline/all", {"type": 9, "code": "600519", "since": "2026-01-01"}),
        ("/index/all", {"type": 9, "code": "   "}),
    ],
)
def test_all_data_routes_validate_parameters(path, params):
    response = client().get(path, params=params)

    assert response.status_code == 400
    assert response.json()["code"] == 1


@pytest.mark.parametrize(
    ("period", "frequency"),
    [
        ("minute", 8),
        ("5minute", 0),
        ("15minute", 1),
        ("30minute", 2),
        ("60minute", 3),
        ("day", 9),
        ("week", 5),
        ("month", 6),
        ("quarter", 10),
        ("year", 11),
    ],
)
def test_stock_kline_period_routes_map_frequencies(period, frequency):
    http = client()

    page = http.get(
        f"/kline/{period}",
        params={"code": "600519", "start": 2, "count": 30},
    )
    all_data = http.get(f"/kline/{period}/all", params={"code": "600519"})

    assert page.status_code == 200
    assert page.json()["data"] == [
        {"symbol": "600519", "frequency": frequency, "start": 2, "offset": 30}
    ]
    assert all_data.status_code == 200
    assert all_data.json()["data"] == [
        {
            "method": "bars_all",
            "symbol": "600519",
            "frequency": frequency,
            "since": None,
        }
    ]


@pytest.mark.parametrize(
    ("period", "frequency"),
    [
        ("minute", 8),
        ("5minute", 0),
        ("15minute", 1),
        ("30minute", 2),
        ("60minute", 3),
        ("day", 9),
    ],
)
def test_index_period_routes_map_frequencies(period, frequency):
    response = client().get(
        f"/index/{period}",
        params={"code": "000001", "start": 4, "count": 20},
    )

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "method": "index",
            "symbol": "000001",
            "frequency": frequency,
            "start": 4,
            "offset": 20,
        }
    ]


@pytest.mark.parametrize(
    ("period", "frequency"),
    [("day", 9), ("week", 5), ("month", 6), ("quarter", 10), ("year", 11)],
)
def test_index_all_period_routes_map_frequencies(period, frequency):
    response = client().get(f"/index/{period}/all", params={"code": "000001"})

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "method": "index_all",
            "symbol": "000001",
            "frequency": frequency,
            "since": None,
        }
    ]


def test_kline_day_all_supports_since_and_adjustment():
    response = client().get(
        "/kline/day/all",
        params={"code": "600519", "since": "20260101", "adjust": "QFQ"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "method": "bars_all",
            "symbol": "600519",
            "frequency": 9,
            "since": "20260101",
            "adjust": "qfq",
        }
    ]


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/kline/minute", {"code": "600519", "start": 65536, "count": 1}),
        ("/kline/year/all", {"code": "   "}),
        ("/kline/day/all", {"code": "600519", "since": "20260230"}),
        ("/kline/day/all", {"code": "600519", "adjust": "forward"}),
        ("/index/day", {"code": "000001", "start": -1, "count": 1}),
        ("/index/year/all", {"code": "   "}),
    ],
)
def test_period_routes_validate_parameters(path, params):
    response = client().get(path, params=params)

    assert response.status_code == 400
    assert response.json()["code"] == 1


def test_stock_info_route_maps_parameters_and_serializes_raw_models():
    response = client().get(
        "/stock/info",
        params={"codes": "sh600519,sz000001", "refresh_industries": "true"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "full_code": "sh600519",
            "security": {"code": "600519", "name": "贵州茅台"},
            "quote": {"price": 20.0},
            "finance": {"ipo_date": "2001-08-27"},
        },
        {
            "full_code": "sz000001",
            "security": {"code": "000001", "name": "平安银行"},
            "quote": {"price": 10.0},
            "finance": None,
        },
    ]


def test_stock_info_route_rejects_empty_codes():
    response = client().get("/stock/info", params={"codes": " , "})

    assert response.status_code == 400
    assert response.json()["code"] == 1


def test_capital_flow_routes():
    res = client().get("/capital_flow", params={"code": "002594", "date": "20260914"})
    assert res.status_code == 200
    assert res.json()["data"][0]["method"] == "capital_flow"
    assert res.json()["data"][0]["symbol"] == "002594"
    assert res.json()["data"][0]["date"] == "20260914"

    res_hist = client().get("/capital_flow/history", params={"code": "002594", "days": 5})
    assert res_hist.status_code == 200
    assert res_hist.json()["data"][0]["method"] == "capital_flow_history"
    assert res_hist.json()["data"][0]["symbol"] == "002594"
    assert res_hist.json()["data"][0]["days"] == 5

    res_sec = client().get("/capital_flow/sector", params={"name": "白酒"})
    assert res_sec.status_code == 200
    assert res_sec.json()["data"][0]["method"] == "sector_capital_flow"
    assert res_sec.json()["data"][0]["name"] == "白酒"
