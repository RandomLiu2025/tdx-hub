"""Helpers for normalized F10 company-information output."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

F10_COLUMNS = (
    "full_code",
    "exchange",
    "market_id",
    "code",
    "section",
    "filename",
    "start",
    "length",
    "content",
)


def normalize_f10_content(content: str | None) -> str:
    """Normalize F10 text layout without changing its character tables."""
    if content is None:
        return ""
    if not isinstance(content, str):
        content = str(content)

    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip("\n")


def f10_frame(records: Iterable[Mapping[str, Any]] = ()) -> pd.DataFrame:
    """Return F10 records with a stable public column order."""
    return pd.DataFrame.from_records(records, columns=F10_COLUMNS)
