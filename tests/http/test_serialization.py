from datetime import UTC, date, datetime

import numpy as np
import pandas as pd

from tdxhub.http.serialization import frame_records, to_jsonable


def test_to_jsonable_converts_scalar_and_special_values():
    value = {
        "integer": np.int64(7),
        "number": np.float64(1.5),
        "missing": np.nan,
        "infinite": float("inf"),
        "date": date(2026, 9, 10),
        "aware": datetime(2026, 9, 10, 8, 30, tzinfo=UTC),
        "raw": b"tdx",
    }

    assert to_jsonable(value) == {
        "integer": 7,
        "number": 1.5,
        "missing": None,
        "infinite": None,
        "date": "2026-09-10",
        "aware": "2026-09-10T08:30:00+00:00",
        "raw": "dGR4",
    }


def test_frame_records_preserves_named_datetime_index_as_rfc3339():
    frame = pd.DataFrame(
        {"close": [10.5, np.nan], "updated": [pd.Timestamp("2026-09-10 15:00"), pd.NaT]},
        index=pd.DatetimeIndex(["2026-09-09 15:00", "2026-09-10 15:00"], name="datetime"),
    )

    assert frame_records(frame) == [
        {
            "datetime": "2026-09-09T15:00:00+08:00",
            "close": 10.5,
            "updated": "2026-09-10T15:00:00+08:00",
        },
        {
            "datetime": "2026-09-10T15:00:00+08:00",
            "close": None,
            "updated": None,
        },
    ]


def test_frame_records_does_not_duplicate_index_column():
    frame = pd.DataFrame(
        {"datetime": ["2026-09-10 15:00"], "close": [10.5]},
        index=pd.DatetimeIndex(["2026-09-10 15:00"], name="datetime"),
    )

    assert frame_records(frame) == [{"datetime": "2026-09-10T15:00:00+08:00", "close": 10.5}]


def test_frame_records_uses_normalized_quote_datetime_without_mutation():
    from tdxhub.utils import to_data

    frame = to_data([{"datetime": "2026-09-10 15:00", "close": 10.5}])
    original = frame.copy(deep=True)

    assert frame_records(frame) == [{"datetime": "2026-09-10T15:00:00+08:00", "close": 10.5}]
    pd.testing.assert_frame_equal(frame, original)


def test_frame_records_preserves_unnamed_aware_datetime_index():
    frame = pd.DataFrame({"close": [10.5]}, index=pd.DatetimeIndex(["2026-09-10 07:00"], tz="UTC"))

    assert frame_records(frame) == [{"datetime": "2026-09-10T07:00:00+00:00", "close": 10.5}]


def test_frame_records_keeps_non_temporal_index_and_arbitrary_strings():
    frame = pd.DataFrame({"label": ["2026-09-10 15:00"]}, index=pd.Index(["000001"], name="code"))

    assert frame_records(frame) == [{"code": "000001", "label": "2026-09-10 15:00"}]
