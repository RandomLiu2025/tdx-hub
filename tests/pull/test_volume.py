import pytest

from tdxhub.pull import from_shares, to_shares


def test_volume_unit_conversion():
    assert to_shares(123) == 12300
    assert from_shares(12300) == 123
    assert from_shares(12349) == 123
    with pytest.raises(TypeError):
        to_shares(1.5)
