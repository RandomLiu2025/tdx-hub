"""Official report units and null values remain correct across JSON output."""
import json

import pandas as pd
import pytest

from tdxhub.http.serialization import to_jsonable
from tdxhub.official import parse_tdxstat, parse_tdxstat2, parse_xgsg


@pytest.mark.parametrize("raw", ["", "bad", "NaN", "inf", "-inf", "1e999"])
@pytest.mark.parametrize("parser,indices", [
    (parse_tdxstat, {3: "pe_ttm", 5: "trend_days", 6: "change_pct", 9: "pe_static", 10: "dividend_yield",
                     28: "change_5d", 30: "change_10d", 18: "change_20d", 20: "change_60d", 21: "change_ytd"}),
    (parse_tdxstat2, {3: "amount", 5: "amount_prev", 16: "ipo_price", 17: "high_52w", 18: "low_52w"}),
    (parse_xgsg, {3: "issue_price"}),
])
def test_report_unknown_numbers_are_null_but_zero_is_preserved(parser, indices, raw):
    fields = [""] * 31
    fields[:3] = ["1", "600666", "20260918"]
    for index in indices:
        fields[index] = raw
    zero = fields.copy()
    zero[1] = "600000"
    for index in indices:
        zero[index] = "0"
    result = parser("|".join(fields) + "\n" + "|".join(zero))
    rows = to_jsonable(result)
    json.dumps(rows, allow_nan=False)
    for column in indices.values():
        assert pd.isna(result.iloc[0][column])
        assert rows[0][column] is None
        assert rows[1][column] == 0
    assert rows[0]["raw_fields"] == fields


def test_report_amounts_are_yuan_even_when_attrs_are_not_serialized():
    fields = [""] * 21
    fields[:6] = ["0", "159729", "20260918", "14.59", "", "35.32"]
    row = to_jsonable(parse_tdxstat2("|".join(fields)))[0]
    assert row["amount"] == pytest.approx(145900)
    assert row["amount_prev"] == pytest.approx(353200)
    assert row["date"] == "20260918"
    assert row["raw_fields"][3] == "14.59"
    assert row["raw_fields"][5] == "35.32"
