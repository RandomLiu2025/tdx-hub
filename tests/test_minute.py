from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from pandas import testing as pdt

from tdxhub.minute import build_minute_241
from tdxhub.quotes import StdQuotes

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _bars(*timestamps, tz=None):
    index = pd.DatetimeIndex(timestamps, name="bar_time", tz=tz)
    frame = pd.DataFrame(
        {
            "open": [10.0 + index for index in range(len(timestamps))],
            "close": [10.2 + index for index in range(len(timestamps))],
            "high": [10.4 + index for index in range(len(timestamps))],
            "low": [9.8 + index for index in range(len(timestamps))],
            "vol": [10000 + index for index in range(len(timestamps))],
            "volume": [10000 + index for index in range(len(timestamps))],
            "amount": [100_000.0 + index for index in range(len(timestamps))],
            "datetime": [timestamp.strftime("%Y-%m-%d %H:%M") for timestamp in index],
            "year": index.year,
            "month": index.month,
            "day": index.day,
            "hour": index.hour,
            "minute": index.minute,
        },
        index=index,
    )
    frame.attrs["source"] = "fixture"
    return frame


def test_build_minute_241_inserts_auction_bar_and_adjusts_0931():
    bars = _bars("2026-09-10 09:31", "2026-09-10 09:32", tz=_SHANGHAI)
    bars["last"] = [9.9, 10.2]
    bars["order"] = [10, 8]
    original = bars.copy(deep=True)
    trades = pd.DataFrame([{"time": "09:25", "price": 10.1, "vol": 20, "num": 3, "buyorsell": 2}])

    result = build_minute_241(bars, {date(2026, 9, 10): trades})

    auction = result.loc[pd.Timestamp("2026-09-10 09:30", tz=_SHANGHAI)]
    assert auction[["open", "close", "high", "low"]].tolist() == [10.1] * 4
    assert auction[["vol", "volume", "amount", "order", "last"]].tolist() == [
        2000,
        2000,
        20_200.0,
        3,
        9.9,
    ]
    first_minute = result.loc[pd.Timestamp("2026-09-10 09:31", tz=_SHANGHAI)]
    assert first_minute[["vol", "volume", "amount", "order", "last"]].tolist() == [
        8000,
        8000,
        79_800.0,
        7,
        10.1,
    ]
    assert auction["datetime"] == "2026-09-10 09:30"
    assert auction[["year", "month", "day", "hour", "minute"]].tolist() == [2026, 9, 10, 9, 30]
    assert result.index.name == "bar_time"
    assert result.index.tz == _SHANGHAI
    assert result.attrs == {"source": "fixture"}
    pdt.assert_frame_equal(bars, original)


def test_build_minute_241_rejects_inconsistent_auction_without_clamping_source():
    bars = _bars("2026-09-09 09:31")
    bars.loc[:, ["vol", "volume"]] = 5
    bars.loc[:, "amount"] = 100.0
    trades = pd.DataFrame([{"time": "09:25", "price": 10.0, "vol": 8, "buyorsell": 2}])
    result = build_minute_241(bars, {"20260909": trades})
    assert result.iloc[0]["auction_status"] == "inconsistent"
    assert pd.isna(result.iloc[0]["close"])
    assert result.iloc[1]["vol"] == 5
    assert result.iloc[1]["amount"] == 100
    assert result.iloc[1]["last"] == 0


def test_build_minute_241_does_not_duplicate_existing_0930():
    bars = _bars("2026-09-09 09:30", "2026-09-09 09:31")
    trades = pd.DataFrame([{"time": "09:25", "price": 10.0, "vol": 8, "buyorsell": 2}])
    result = build_minute_241(bars, {date(2026, 9, 9): trades})
    assert list(result.index.strftime("%H:%M")) == ["09:30", "09:31"]
    pdt.assert_frame_equal(result[bars.columns], bars)


def test_build_minute_241_handles_each_date_independently_and_derives_last():
    bars = _bars(
        "2026-09-08 15:00",
        "2026-09-09 09:31",
        "2026-09-09 09:32",
        "2026-09-10 09:31",
    )
    trades = {
        date(2026, 9, 9): pd.DataFrame([{"time": "09:25", "price": 11.0, "vol": 1, "num": 1, "buyorsell": 2}]),
        date(2026, 9, 10): pd.DataFrame([{"time": "09:25", "price": 13.0, "vol": 2, "num": 2, "buyorsell": 2}]),
    }

    result = build_minute_241(bars, trades)

    assert list(result.index.strftime("%Y-%m-%d %H:%M")) == [
        "2026-09-08 15:00",
        "2026-09-09 09:30",
        "2026-09-09 09:31",
        "2026-09-09 09:32",
        "2026-09-10 09:30",
        "2026-09-10 09:31",
    ]
    assert result.loc["2026-09-09 09:30", "last"] == bars.iloc[0]["close"]
    assert result.loc["2026-09-10 09:30", "last"] == bars.iloc[2]["close"]
    assert result.loc["2026-09-09 09:31", "last"] == 11.0
    assert result.loc["2026-09-10 09:31", "last"] == 13.0


def test_build_minute_241_empty_data_returns_independent_copy():
    bars = pd.DataFrame()
    bars.attrs["source"] = "empty"

    result = build_minute_241(bars, {})

    assert result.empty
    assert result is not bars
    assert result.attrs == bars.attrs


def test_std_quotes_minute_241_fetches_current_and_historical_trades(monkeypatch):
    quotes = object.__new__(StdQuotes)
    calls = []
    bars = _bars("2026-09-10 09:31", "2026-09-11 09:31")

    def bars_all(**kwargs):
        calls.append(("bars_all", kwargs))
        return bars

    def transaction_all(**kwargs):
        calls.append(("transaction_all", kwargs))
        return pd.DataFrame([{"time": "09:25", "price": 11.0, "vol": 2, "num": 1, "buyorsell": 2}])

    def transactions_all(**kwargs):
        calls.append(("transactions_all", kwargs))
        return pd.DataFrame([{"time": "09:25", "price": 10.0, "vol": 1, "buyorsell": 2}])

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert str(tz) == "Asia/Shanghai"
            return datetime(2026, 9, 11, 8, tzinfo=tz)

    monkeypatch.setattr(quotes, "bars_all", bars_all)
    monkeypatch.setattr(quotes, "transaction_all", transaction_all)
    monkeypatch.setattr(quotes, "transactions_all", transactions_all)
    monkeypatch.setattr("tdxhub.quotes.datetime", Clock)

    result = quotes.minute_241("600519", since="20260910")

    assert calls == [
        ("bars_all", {"symbol": "600519", "frequency": 8, "since": "20260910"}),
        ("transactions_all", {"symbol": "600519", "date": "20260910"}),
        ("transaction_all", {"symbol": "600519"}),
    ]
    assert result.loc["2026-09-10 09:31", "last"] == 10.0
    assert result.loc["2026-09-11 09:31", "last"] == 11.0


def test_std_quotes_minute_241_without_since_returns_only_latest_trade_date(monkeypatch):
    quotes = object.__new__(StdQuotes)
    calls = []
    bars = _bars(
        "2026-09-10 09:31",
        "2026-09-10 15:00",
        "2026-09-11 09:31",
        "2026-09-11 09:32",
    )

    def bars_all(**kwargs):
        calls.append(("bars_all", kwargs))
        return bars

    def transaction_all(**kwargs):
        calls.append(("transaction_all", kwargs))
        return pd.DataFrame([{"time": "09:25", "price": 12.0, "vol": 2, "num": 1}])

    def unexpected(**kwargs):
        raise AssertionError(f"unexpected historical transaction request: {kwargs}")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert str(tz) == "Asia/Shanghai"
            return datetime(2026, 9, 11, 10, tzinfo=tz)

    monkeypatch.setattr(quotes, "bars_all", bars_all)
    monkeypatch.setattr(quotes, "transaction_all", transaction_all)
    monkeypatch.setattr(quotes, "transactions_all", unexpected)
    monkeypatch.setattr("tdxhub.quotes.datetime", Clock)

    result = quotes.minute_241("600519")

    assert calls == [
        ("bars_all", {"symbol": "600519", "frequency": 8, "since": None}),
        ("transaction_all", {"symbol": "600519"}),
    ]
    assert list(result.index.strftime("%Y-%m-%d %H:%M")) == [
        "2026-09-11 09:30",
        "2026-09-11 09:31",
        "2026-09-11 09:32",
    ]


def test_std_quotes_minute_241_does_not_fetch_trades_for_empty_bars(monkeypatch):
    quotes = object.__new__(StdQuotes)
    calls = []

    def bars_all(**kwargs):
        calls.append(("bars_all", kwargs))
        return pd.DataFrame()

    def unexpected(**kwargs):
        raise AssertionError(f"unexpected trade request: {kwargs}")

    monkeypatch.setattr(quotes, "bars_all", bars_all)
    monkeypatch.setattr(quotes, "transaction_all", unexpected)
    monkeypatch.setattr(quotes, "transactions_all", unexpected)

    result = quotes.minute_241("600519")

    assert result.empty
    assert calls == [("bars_all", {"symbol": "600519", "frequency": 8, "since": None})]


def _minute_points(count: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "price": [10.0 + position / 100 for position in range(count)],
            "vol": list(range(count)),
            "volume": list(range(count)),
        }
    )


def test_attach_minute_timestamps_builds_full_a_share_session_without_mutation():
    from tdxhub.minute import attach_minute_timestamps

    points = _minute_points(240)
    points.attrs["source"] = "fixture"
    original = points.copy(deep=True)

    result = attach_minute_timestamps(points, "20260911")

    assert isinstance(result.index, pd.DatetimeIndex)
    assert result.index.name == "datetime"
    assert result["datetime"].tolist() == result.index.tolist()
    assert result.index[[0, 119, 120, 239]].strftime("%Y-%m-%d %H:%M").tolist() == [
        "2026-09-11 09:31",
        "2026-09-11 11:30",
        "2026-09-11 13:01",
        "2026-09-11 15:00",
    ]
    assert result.attrs == {"source": "fixture"}
    pdt.assert_frame_equal(points, original)


def test_attach_minute_timestamps_maps_partial_response_from_market_open():
    from tdxhub.minute import attach_minute_timestamps

    result = attach_minute_timestamps(_minute_points(121), date(2026, 9, 11))

    assert result.index[-2:].strftime("%H:%M").tolist() == ["11:30", "13:01"]


def test_attach_minute_timestamps_returns_stable_empty_schema():
    from tdxhub.minute import attach_minute_timestamps

    points = pd.DataFrame(columns=["price", "vol", "volume"])

    result = attach_minute_timestamps(points, "20260911")

    assert result.empty
    assert list(result.columns) == ["price", "vol", "volume", "datetime"]
    assert isinstance(result.index, pd.DatetimeIndex)
    assert result.index.name == "datetime"


def test_attach_minute_timestamps_rejects_more_than_one_trading_day():
    from tdxhub.minute import attach_minute_timestamps

    with pytest.raises(ValueError, match="240"):
        attach_minute_timestamps(_minute_points(241), "20260911")


def test_std_quotes_minutes_adds_requested_date_time_axis():
    class MinuteClient:
        def __init__(self):
            self.calls = []

        def get_history_minute_time_data(self, **kwargs):
            self.calls.append(kwargs)
            return [{"price": 10.1, "vol": 3}, {"price": 10.2, "vol": 4}]

    quotes = object.__new__(StdQuotes)
    quotes.client = MinuteClient()

    result = quotes.minutes("300394", date="20260911")

    assert quotes.client.calls == [{"market": 0, "code": "300394", "date": "20260911"}]
    assert result.index.strftime("%Y-%m-%d %H:%M").tolist() == [
        "2026-09-11 09:31",
        "2026-09-11 09:32",
    ]
    assert result["datetime"].tolist() == result.index.tolist()
    assert result[["price", "vol", "volume"]].to_dict("records") == [
        {"price": 10.1, "vol": 3, "volume": 3},
        {"price": 10.2, "vol": 4, "volume": 4},
    ]


def test_std_quotes_minute_uses_shanghai_trade_date(monkeypatch):
    quotes = object.__new__(StdQuotes)
    calls = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert str(tz) == "Asia/Shanghai"
            return datetime(2026, 9, 11, 0, 30, tzinfo=tz)

    def minutes(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame()

    monkeypatch.setattr("tdxhub.quotes.datetime", Clock)
    monkeypatch.setattr(quotes, "minutes", minutes)

    quotes.minute("300394")

    assert calls == [{"symbol": "300394", "date": "20260911"}]


def test_auction_skips_indicative_records_and_converts_lots_to_shares():
    bars = _bars('2026-09-18 09:31', '2026-09-18 09:32')
    bars.loc[:, ['vol', 'volume']] = 1_911_500
    bars.loc[:, 'amount'] = 22_137_400.0
    bars.loc[:, ['open', 'close']] = 11.59
    bars.loc[:, 'low'] = 11.56
    bars.loc[:, 'high'] = 11.60
    trades = pd.DataFrame([
        {'time': '09:15', 'price': 11.61, 'vol': 0, 'buyorsell': 8},
        {'time': '09:25', 'price': 11.59, 'vol': 0, 'buyorsell': 8},
        {'time': '09:25', 'price': 11.59, 'vol': 3739, 'buyorsell': 2},
        {'time': '09:31', 'price': 11.58, 'vol': 1, 'buyorsell': 0},
    ])
    result = build_minute_241(bars, {'20260918': trades})
    assert result.iloc[0]['close'] == 11.59
    assert result.iloc[0]['vol'] == 373900
    assert result.iloc[0]['amount'] == pytest.approx(4_333_501)
    assert result.iloc[0]['auction_status'] == 'derived'
    assert result.iloc[1]['vol'] == 1_537_600
    assert result['vol'].sum() == bars['vol'].sum()
    assert result['amount'].sum() == pytest.approx(bars['amount'].sum())


def test_missing_auction_is_null_not_zero_price_and_leaves_first_minute_unchanged():
    bars = _bars('2026-09-18 09:31')
    result = build_minute_241(bars, {})
    assert result.iloc[0][['open', 'high', 'low', 'close']].isna().all()
    assert result.iloc[0]['auction_status'] == 'missing'
    assert result.iloc[0]['vol'] == 0
    assert result.iloc[1]['vol'] == bars.iloc[0]['vol']
    assert result.iloc[1]['last'] == 0


@pytest.mark.parametrize('field,value', [('amount', float('inf')), ('amount', float('nan')),
                                        ('vol', float('inf')), ('low', float('nan')),
                                        ('high', float('inf'))])
def test_auction_does_not_derive_against_nonfinite_source_bar(field, value):
    bars = _bars('2026-09-18 09:31')
    bars[field] = value
    trades = pd.DataFrame([{'time': '09:25', 'price': 10., 'vol': 1, 'buyorsell': 2}])
    result = build_minute_241(bars, {'20260918': trades})
    assert result.iloc[0]['auction_status'] == 'inconsistent'
    assert pd.isna(result.iloc[0]['close'])
    assert result.iloc[1]['amount'] == bars.iloc[0]['amount'] or pd.isna(bars.iloc[0]['amount'])


def test_auction_overflow_is_inconsistent_and_preserves_source():
    bars = _bars('2026-09-18 09:31')
    trades = pd.DataFrame([{'time': '09:25', 'price': 10., 'vol': 1e308, 'buyorsell': 2}])
    result = build_minute_241(bars, {'20260918': trades})
    assert result.iloc[0]['auction_status'] == 'inconsistent'
    assert pd.isna(result.iloc[0]['close'])
    assert result.iloc[1]['vol'] == bars.iloc[0]['vol']
