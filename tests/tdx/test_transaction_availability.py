"""Trade availability must be determined by the server, not the local clock."""
from datetime import datetime
from unittest.mock import Mock

import pytest

from tdxhub.tdx import client as client_module
from tdxhub.tdx import codec
from tdxhub.tdx.client import StandardClient
from tdxhub.tdx.errors import TdxFunctionCallError


@pytest.mark.parametrize("hour,minute", [(8, 0), (9, 30), (11, 30), (12, 0), (13, 0), (15, 0), (21, 0)])
def test_transaction_queries_server_outside_local_trading_hours(monkeypatch, hour, minute):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 21, hour, minute, tzinfo=tz)

    monkeypatch.setattr(codec, "datetime", Clock)
    rows = [{"time": "15:00", "price": 3.53, "vol": 31, "num": 1, "buyorsell": 2}]
    command = Mock()
    command.call_api.return_value = rows
    factory = Mock(return_value=command)
    monkeypatch.setattr(client_module, "GetTransactionData", factory)
    client = StandardClient(auto_retry=False, raise_exception=True)

    assert client.get_transaction_data(1, "600666", 0, 100) == rows
    factory.assert_called_once_with(client.client, lock=client.lock)
    command.setParams.assert_called_once_with(1, "600666", 0, 100)
    command.call_api.assert_called_once_with()


def test_transaction_keeps_transport_errors_distinct_from_empty_response(monkeypatch):
    command = Mock()
    command.call_api.side_effect = TimeoutError("server timed out")
    monkeypatch.setattr(client_module, "GetTransactionData", Mock(return_value=command))
    client = StandardClient(auto_retry=False, raise_exception=True)
    with pytest.raises(TdxFunctionCallError, match="server timed out"):
        client.get_transaction_data(0, "000001", 0, 100)
    command.call_api.side_effect = None
    command.call_api.return_value = []
    assert client.get_transaction_data(0, "000001", 0, 100) == []
