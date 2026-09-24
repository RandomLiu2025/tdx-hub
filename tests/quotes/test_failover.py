from __future__ import annotations

from collections import deque

import pytest

from tdxhub.failover import EndpointPool, FailoverClient
from tdxhub.tdx.errors import TdxFunctionCallError, ValidationException

A = ("127.0.0.1", 7709)
B = ("127.0.0.2", 7709)
C = ("127.0.0.3", 7709)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class ScriptedApi:
    def __init__(self, scripts, connections):
        self.scripts = scripts
        self.connections = connections
        self.endpoint = None
        self.client = None
        self.closed = True

    def connect(self, ip, port, time_out):
        self.endpoint = (ip, port)
        self.connections.append((self.endpoint, time_out))
        self.client = object()
        self.closed = False
        return self

    def close(self):
        self.client = None
        self.closed = True

    def get_security_bars(self, *args):
        action = self.scripts[self.endpoint].popleft()
        if isinstance(action, BaseException):
            raise action
        return action


def client_for(scripts, *, max_failovers=2, raise_exception=True, clock=None, switched=None):
    connections = []
    scripts = {endpoint: deque(values) for endpoint, values in scripts.items()}
    pool = EndpointPool([A, B, C], cooldown=60, clock=clock)
    client = FailoverClient(
        pool,
        lambda: ScriptedApi(scripts, connections),
        timeout=3,
        max_failovers=max_failovers,
        raise_exception=raise_exception,
        on_switch=switched.append if switched is not None else None,
    )
    client.connect()
    return client, connections


def test_endpoint_pool_deduplicates_and_honours_cooldown():
    clock = FakeClock()
    pool = EndpointPool([A, A, B], cooldown=30, clock=clock)

    pool.report_failure(A, ConnectionError("offline"))

    assert pool.available() == [B]
    assert pool.snapshot(current=B)[0] == {
        "server": A,
        "active": False,
        "failures": 1,
        "cooldown_remaining": 30.0,
        "last_error": "offline",
    }

    clock.now += 31
    assert pool.available() == [A, B]


def test_request_failure_switches_server_and_replays_call_once():
    switched = []
    client, connections = client_for(
        {
            A: [TdxFunctionCallError("broken packet")],
            B: [[{"close": 2.0}]],
            C: [],
        },
        switched=switched,
    )

    result = client.get_security_bars(9, 1, "600000", 0, 1)

    assert result == [{"close": 2.0}]
    assert connections == [(A, 3), (B, 3)]
    assert client.endpoint == B
    assert switched == [A, B]
    statuses = client.server_status()
    assert statuses[0]["failures"] == 1
    assert statuses[1]["active"] is True


def test_validation_error_does_not_switch_server():
    client, connections = client_for(
        {A: [ValidationException("bad symbol")], B: [[{"close": 2.0}]], C: []}
    )

    with pytest.raises(ValidationException, match="bad symbol"):
        client.get_security_bars(9, 1, "bad", 0, 1)

    assert connections == [(A, 3)]
    assert client.endpoint == A


def test_failover_budget_limits_cross_server_attempts():
    client, connections = client_for(
        {
            A: [TdxFunctionCallError("a")],
            B: [TdxFunctionCallError("b")],
            C: [[{"close": 3.0}]],
        },
        max_failovers=1,
    )

    with pytest.raises(TdxFunctionCallError, match="b"):
        client.get_security_bars(9, 1, "600000", 0, 1)

    assert connections == [(A, 3), (B, 3)]


def test_exhausted_failover_returns_none_in_non_raising_mode():
    client, connections = client_for(
        {
            A: [TdxFunctionCallError("a")],
            B: [TdxFunctionCallError("b")],
            C: [TdxFunctionCallError("c")],
        },
        max_failovers=2,
        raise_exception=False,
    )

    assert client.get_security_bars(9, 1, "600000", 0, 1) is None
    assert connections == [(A, 3), (B, 3), (C, 3)]


def test_close_and_raw_attributes_are_proxied():
    client, _ = client_for({A: [[{"close": 1.0}]], B: [], C: []})

    assert client.closed is False
    assert client.client is not None

    client.close()

    assert client.closed is True
    assert client.client is None


def test_strict_client_re_raises_last_error_while_all_servers_are_cooling_down():
    client, _ = client_for(
        {
            A: [TdxFunctionCallError("a")],
            B: [TdxFunctionCallError("b")],
            C: [TdxFunctionCallError("c")],
        },
        max_failovers=2,
    )

    with pytest.raises(TdxFunctionCallError, match="c"):
        client.get_security_bars(9, 1, "600000", 0, 1)
    with pytest.raises(TdxFunctionCallError, match="c"):
        client.get_security_bars(9, 1, "600000", 0, 1)


def test_fork_shares_health_state_but_not_connection():
    client, _ = client_for({A: [[{"close": 1.0}]], B: [], C: []})

    forked = client.fork()

    assert forked is not client
    assert forked.endpoint_pool is client.endpoint_pool
    assert forked.client_factory is client.client_factory
    assert forked.is_connected is False
    assert forked.endpoint is None


class ForkablePoolClient:
    def __init__(self, created):
        self.created = created
        self.closed = False
        self.created.append(self)

    def fork(self):
        return ForkablePoolClient(self.created)

    def close(self):
        self.closed = True


def test_failover_client_pool_bounds_reuses_and_closes_connections():
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from tdxhub.failover import FailoverClientPool

    created = []
    template = ForkablePoolClient(created)
    pool = FailoverClientPool(template, max_size=2)
    release = threading.Event()
    both_active = threading.Event()
    state_lock = threading.Lock()
    active = 0
    max_active = 0
    used = []

    def borrow():
        nonlocal active, max_active
        with pool.connection() as client:
            with state_lock:
                active += 1
                max_active = max(max_active, active)
                used.append(client)
                if active == 2:
                    both_active.set()
            assert release.wait(timeout=2)
            with state_lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(borrow) for _ in range(4)]
        assert both_active.wait(timeout=2)
        assert len(created) == 2
        release.set()
        for future in futures:
            future.result(timeout=2)

    assert max_active == 2
    assert len({id(client) for client in used}) == 2

    pool.close()

    assert all(client.closed for client in created)
    with pytest.raises(RuntimeError, match="连接池已关闭"), pool.connection():
        pass


def test_failover_client_pool_defers_closing_borrowed_connection():
    import threading

    from tdxhub.failover import FailoverClientPool

    created = []
    template = ForkablePoolClient(created)
    pool = FailoverClientPool(template, max_size=1)
    borrowed = threading.Event()
    release = threading.Event()

    def borrow():
        with pool.connection() as client:
            borrowed.set()
            assert release.wait(timeout=2)
            assert client.closed is False

    worker = threading.Thread(target=borrow)
    worker.start()
    assert borrowed.wait(timeout=2)

    pool.close()

    assert template.closed is False
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert template.closed is True
