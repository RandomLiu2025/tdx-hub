import threading

import pytest

from tdxhub.failover import EndpointPool, FailoverClient
from tdxhub.tdx.client import StandardClient
from tdxhub.tdx.deadline import LockTimeout, remaining, request_budget, socket_budget
from tdxhub.tdx.errors import ResponseHeaderRecvFails, TdxFunctionCallError
from tdxhub.tdx.protocol.raw_parser import RawParser
from tests.quotes.test_failover import A, B, FakeClock, ScriptedApi
from tests.tdx.test_transport import StreamSocket, frame


class TimedSocket(StreamSocket):
    def __init__(self, clock, data=None, **kwargs):
        super().__init__(data or frame(b"payload"), **kwargs)
        self.clock = clock
        self.timeout = 15
        self.timeouts = []
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def gettimeout(self):
        return self.timeout

    def recv(self, size):
        self.timeouts.append(self.timeout)
        self.clock.now += 0.5
        return super().recv(size)

    def close(self):
        self.closed = True

    def shutdown(self, *args):
        pass


def test_slow_fragmented_response_cannot_reset_request_budget():
    clock = FakeClock()
    sock = TimedSocket(clock, chunk=1)
    parser = RawParser(sock)
    parser.setParams(b"request")
    with pytest.raises(ResponseHeaderRecvFails, match="deadline"), request_budget(2, clock):
        parser.call_api()
    assert sock.timeouts == [2, 1.5, 1, 0.5]
    assert sock.timeout == 15
    assert remaining() is None


def test_connect_and_setup_share_budget_and_close_on_failure(monkeypatch):
    clock = FakeClock()

    class Sock(TimedSocket):
        def connect(self, endpoint):
            assert self.timeout == 2
            clock.now += 1

    sock = Sock(clock, chunk=1)
    monkeypatch.setattr("tdxhub.tdx.transport.TrafficStatSocket", lambda *args: sock)
    api = StandardClient(raise_exception=True)
    with pytest.raises(TdxFunctionCallError, match="deadline"), request_budget(2, clock):
        api.connect(*A, time_out=15)
    assert sock.closed
    assert api.client is None
    assert sock.timeouts == [1, 0.5]


def test_socket_timeout_restored_on_failure_and_nested_budget_does_not_extend():
    clock = FakeClock()
    sock = TimedSocket(clock)
    with request_budget(3, clock):
        clock.now += 1
        with request_budget(10, clock):
            assert remaining() == 2
            with pytest.raises(OSError), socket_budget(sock):
                assert sock.timeout == 2
                raise OSError("offline")
        assert remaining() == 2
    assert sock.timeout == 15
    assert remaining() is None


def test_protocol_lock_timeout_is_local_and_does_not_send():
    lock = threading.Lock()
    lock.acquire()
    sock = StreamSocket(frame(b"payload"))
    parser = RawParser(sock, lock=lock)
    parser.setParams(b"request")
    try:
        with pytest.raises(LockTimeout), request_budget(0.02):
            parser.call_api()
    finally:
        lock.release()
    assert sock.sent == b""


def test_failed_request_does_not_refresh_ack_time():
    api = StandardClient(raise_exception=True)
    api.last_ack_time = 1
    api.client = StreamSocket(b"")
    with pytest.raises(TdxFunctionCallError):
        api.get_security_bars(9, 1, "600000", 0, 1)
    assert api.last_ack_time == 1
    api.client = StreamSocket(frame(b"\0\0"))
    assert api.get_security_bars(9, 1, "600000", 0, 1) == []
    assert api.last_ack_time > 1


def test_heartbeat_thread_reports_failure_and_exits_without_self_join():
    from tdxhub.tdx.heartbeat import HeartBeatThread

    class Api(ScriptedApi):
        def do_heartbeat(self):
            raise ConnectionError("heartbeat offline")

    proxy = FailoverClient(EndpointPool([A, B]), lambda: Api({}, []))
    proxy.connect()
    api = proxy._client
    api.last_ack_time = 0
    stop = threading.Event()
    thread = HeartBeatThread(api, stop, interval=0.001)
    thread.start()
    thread.join(1)
    assert not thread.is_alive()
    assert not proxy.is_connected
    assert proxy.endpoint_pool.available() == [B]
    assert proxy.server_status()[0]["failures"] == 1


def test_busy_foreground_request_does_not_quarantine_or_stop_heartbeat():
    proxy = FailoverClient(EndpointPool([A]), lambda: ScriptedApi({}, []), request_timeout=0.02)
    proxy.connect()
    ready, release = threading.Event(), threading.Event()

    def hold_lock():
        with proxy._lock:
            ready.set()
            release.wait(1)

    thread = threading.Thread(target=hold_lock)
    thread.start()
    try:
        assert ready.wait(1)
        assert proxy._run_heartbeat(proxy._client) is None
    finally:
        release.set()
        thread.join(1)
    assert proxy.is_connected
    assert proxy.endpoint_pool.available() == [A]
    proxy.close()


def test_disconnect_closes_socket_even_when_shutdown_fails():
    class Sock(TimedSocket):
        def shutdown(self, *args):
            raise OSError("not connected")

    from tdxhub.tdx.errors import TdxConnectionError

    api = StandardClient(raise_exception=True)
    sock = Sock(FakeClock())
    api.client = sock
    with pytest.raises(TdxConnectionError):
        api.close()
    assert sock.closed
    assert api.client is None
    assert api.closed


def test_wrapped_heartbeat_parser_lock_timeout_is_not_remote_failure():
    class Api(StandardClient):
        def connect(self, *args, **kwargs):
            self.client = StreamSocket(frame(b"\0\0"))
            return self

        def close(self):
            self.client = None

    api = Api(multithread=True, raise_exception=True)
    proxy = FailoverClient(EndpointPool([A]), lambda: api, request_timeout=0.02)
    proxy.connect()
    api.lock.acquire()
    try:
        proxy._run_heartbeat(api)
    finally:
        api.lock.release()
    assert proxy.is_connected
    assert proxy.server_status()[0]["failures"] == 0
    proxy.close()
