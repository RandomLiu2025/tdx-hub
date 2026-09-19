from __future__ import annotations

from struct import pack

import pandas as pd
import pytest

from tdxhub.reader import StdReader


def _write_delisted(path, records):
    payload = bytearray(b"\x00" * 10 + pack("<I", len(records)))
    for date, open_, high, low, close, amount, volume in records:
        payload.extend(pack("<I5fI4x", date, open_, high, low, close, amount, volume))
    path.write_bytes(payload)


def test_delisted_daily_reads_tdx_cache_and_normalizes_volume(tmp_path):
    (tmp_path / "vipdoc").mkdir()
    cache = tmp_path / "T0002" / "ds_cache"
    cache.mkdir(parents=True)
    filepath = cache / "100#T600001.~~~day"
    _write_delisted(
        filepath,
        [
            (20240102, 1.25, 1.5, 1.0, 1.4, 123456.0, 12800),
            (20240103, 1.4, 1.6, 1.3, 1.55, 234567.0, 25600),
        ],
    )
    reader = StdReader(tmp_path)

    result = reader.delisted_daily("T600001")

    assert list(result.columns) == ["open", "high", "low", "close", "amount", "volume"]
    assert result.index.equals(pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="date"))
    assert result.iloc[0].to_dict() == {
        "open": pytest.approx(1.25),
        "high": pytest.approx(1.5),
        "low": pytest.approx(1.0),
        "close": pytest.approx(1.4),
        "amount": pytest.approx(123456.0),
        "volume": pytest.approx(128.0),
    }
    assert result.attrs == {
        "source": "local_delisted",
        "source_path": str(filepath),
        "symbol": "T600001",
    }
    assert reader.find_path("100#T600001", subdir="ds_cache", suffix="~~~day") == filepath


def test_delisted_daily_returns_empty_when_cache_is_missing(tmp_path):
    (tmp_path / "vipdoc").mkdir()

    result = StdReader(tmp_path).delisted_daily("T600001")

    assert result.empty
    assert result.attrs["source"] == "local_delisted"


def test_delisted_daily_rejects_truncated_cache(tmp_path):
    (tmp_path / "vipdoc").mkdir()
    cache = tmp_path / "T0002" / "ds_cache"
    cache.mkdir(parents=True)
    (cache / "100#T600001.~~~day").write_bytes(b"\x00" * 10 + pack("<I", 2) + b"short")

    with pytest.raises(ValueError, match="记录数 2 超出文件大小"):
        StdReader(tmp_path).delisted_daily("600001")
