"""Explicit conversions between TDX lots and normalized shares."""


def to_shares(lots: int) -> int:
    if not isinstance(lots, int) or isinstance(lots, bool):
        raise TypeError("lots must be an integer")
    return lots * 100


def from_shares(shares: int) -> int:
    if not isinstance(shares, int) or isinstance(shares, bool):
        raise TypeError("shares must be an integer")
    return shares // 100
