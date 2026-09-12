"""JSON serialization helpers for market-data HTTP responses."""

from __future__ import annotations

import base64
import math
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

_LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _datetime_to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=_LOCAL_TIMEZONE)
    return value.isoformat()


def to_jsonable(value: Any) -> Any:
    """Recursively convert pandas, NumPy, and Python values to JSON-safe values."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None

    if isinstance(value, pd.DataFrame):
        return frame_records(value)
    if isinstance(value, pd.Series):
        return [to_jsonable(item) for item in value.tolist()]

    if isinstance(value, np.generic):
        return to_jsonable(value.item())

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, datetime):
        return _datetime_to_iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()

    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")

    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(asdict(value))

    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]

    return value


def frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Use the normalized time index as the canonical RFC3339 timestamp."""
    normalized = frame
    index_name = frame.index.name
    if isinstance(frame.index, pd.DatetimeIndex):
        normalized = frame.copy()
        normalized[index_name or "datetime"] = frame.index
    elif index_name is not None and index_name not in frame.columns:
        normalized = frame.reset_index()

    return [
        {str(key): to_jsonable(value) for key, value in record.items()}
        for record in normalized.to_dict(orient="records")
    ]
