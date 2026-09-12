"""Single-connection runtime failover for TDX quote clients."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import Any

from tdxpy.exceptions import TdxConnectionError, TdxFunctionCallError

Endpoint = tuple[str, int]
_RETRYABLE_ERRORS = (OSError, TdxConnectionError, TdxFunctionCallError)


@dataclass
class _EndpointState:
    endpoint: Endpoint
    failures: int = 0
    cooldown_until: float = 0.0
    last_error: str | None = None


class EndpointPool:
    """Track ordered endpoints and temporarily quarantine failed servers."""

    def __init__(
        self,
        endpoints: Iterable[Endpoint],
        *,
        cooldown: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if cooldown < 0:
            raise ValueError("cooldown 必须大于等于 0")

        self.cooldown = float(cooldown)
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._states: dict[Endpoint, _EndpointState] = {}
        for address, port in endpoints:
            endpoint = (str(address), int(port))
            self._states.setdefault(endpoint, _EndpointState(endpoint))

    def available(self) -> list[Endpoint]:
        """Return endpoints whose cooldown has elapsed, preserving order."""

        now = self._clock()
        with self._lock:
            return [state.endpoint for state in self._states.values() if state.cooldown_until <= now]

    def report_failure(self, endpoint: Endpoint, error: BaseException) -> None:
        """Record a failed request and start the endpoint cooldown."""

        with self._lock:
            state = self._states[endpoint]
            state.failures += 1
            state.cooldown_until = self._clock() + self.cooldown
            state.last_error = str(error)

    def report_success(self, endpoint: Endpoint) -> None:
        """Clear previous failures after a successful connection/request."""

        with self._lock:
            state = self._states[endpoint]
            state.failures = 0
            state.cooldown_until = 0.0
            state.last_error = None

    def snapshot(self, *, current: Endpoint | None = None) -> list[dict[str, Any]]:
        """Return a serializable health snapshot for observability."""

        now = self._clock()
        with self._lock:
            return [
                {
                    "server": state.endpoint,
                    "active": state.endpoint == current,
                    "failures": state.failures,
                    "cooldown_remaining": max(0.0, state.cooldown_until - now),
                    "last_error": state.last_error,
                }
                for state in self._states.values()
            ]


class FailoverClient:
    """Proxy one active TDX client and fail over on transport/protocol errors."""

    def __init__(
        self,
        endpoint_pool: EndpointPool,
        client_factory: Callable[[], Any],
        *,
        timeout: float = 3,
        max_failovers: int = 2,
        raise_exception: bool = True,
        on_switch: Callable[[Endpoint], None] | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if max_failovers < 0:
            raise ValueError("max_failovers 必须大于等于 0")

        self.endpoint_pool = endpoint_pool
        self.client_factory = client_factory
        self.timeout = timeout
        self.max_failovers = int(max_failovers)
        self.raise_exception = bool(raise_exception)
        self.on_switch = on_switch
        self.endpoint: Endpoint | None = None
        self._client: Any = None
        self._connected = False
        self._last_error: BaseException | None = None
        self._lock = threading.RLock()

    def _close_current(self) -> None:
        client = self._client
        self._connected = False
        if client is not None and hasattr(client, "close"):
            # A broken transport may make tdxpy.disconnect() fail as well.
            with suppress(Exception):
                client.close()

    def _connect_endpoint(self, endpoint: Endpoint) -> bool:
        client = self.client_factory()
        try:
            connected = client.connect(*endpoint, time_out=self.timeout)
            if not connected:
                raise TdxConnectionError(f"无法连接行情服务器 {endpoint[0]}:{endpoint[1]}")
        except _RETRYABLE_ERRORS:
            if hasattr(client, "close"):
                with suppress(Exception):
                    client.close()
            raise

        self._client = client
        self.endpoint = endpoint
        self._connected = True
        self._last_error = None
        self.endpoint_pool.report_success(endpoint)
        if self.on_switch is not None:
            self.on_switch(endpoint)
        return True

    def connect(self) -> bool:
        """Connect to the first currently available endpoint."""

        with self._lock:
            if self._connected:
                return True

            last_error: BaseException | None = None
            endpoints = self.endpoint_pool.available()[: self.max_failovers + 1]
            for endpoint in endpoints:
                try:
                    return self._connect_endpoint(endpoint)
                except _RETRYABLE_ERRORS as exc:
                    self.endpoint_pool.report_failure(endpoint, exc)
                    last_error = exc
                    self._last_error = exc

            if self.raise_exception:
                error = last_error or self._last_error
                if error is not None:
                    raise error
                raise TdxConnectionError("当前没有可用的行情服务器")
            return False

    @property
    def is_connected(self) -> bool:
        """Whether the proxy currently owns a connected raw client."""

        return self._connected

    def close(self) -> None:
        with self._lock:
            self._close_current()

    def fork(self) -> FailoverClient:
        """Create an unconnected proxy sharing endpoint health and configuration."""

        return type(self)(
            self.endpoint_pool,
            self.client_factory,
            timeout=self.timeout,
            max_failovers=self.max_failovers,
            raise_exception=self.raise_exception,
            on_switch=self.on_switch,
        )

    def server_status(self) -> list[dict[str, Any]]:
        current = self.endpoint if self._connected else None
        return self.endpoint_pool.snapshot(current=current)

    def _invoke(self, name: str, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            if not self._connected and not self.connect():
                return None

            attempted: set[Endpoint] = set()
            failovers = 0
            last_error: BaseException | None = None

            while self.endpoint is not None and self._connected:
                endpoint = self.endpoint
                attempted.add(endpoint)
                method = getattr(self._client, name)
                try:
                    result = method(*args, **kwargs)
                except _RETRYABLE_ERRORS as exc:
                    self.endpoint_pool.report_failure(endpoint, exc)
                    self._close_current()
                    last_error = exc
                    self._last_error = exc
                else:
                    self.endpoint_pool.report_success(endpoint)
                    self._last_error = None
                    return result

                while failovers < self.max_failovers:
                    next_endpoint = next(
                        (candidate for candidate in self.endpoint_pool.available() if candidate not in attempted),
                        None,
                    )
                    if next_endpoint is None:
                        break

                    attempted.add(next_endpoint)
                    failovers += 1
                    try:
                        self._connect_endpoint(next_endpoint)
                        break
                    except _RETRYABLE_ERRORS as exc:
                        self.endpoint_pool.report_failure(next_endpoint, exc)
                        last_error = exc
                        self._last_error = exc

                if not self._connected:
                    break

            if self.raise_exception and last_error is not None:
                raise last_error
            return None

    def __getattr__(self, name: str) -> Any:
        client = self.__dict__.get("_client")
        if client is None:
            raise AttributeError(name)
        attribute = getattr(client, name)
        if not callable(attribute):
            return attribute

        def call(*args: Any, **kwargs: Any) -> Any:
            return self._invoke(name, *args, **kwargs)

        return call


class FailoverClientPool:
    """Bounded pool of independent failover clients sharing endpoint health."""

    def __init__(self, client: FailoverClient, *, max_size: int = 4) -> None:
        if isinstance(max_size, bool) or not isinstance(max_size, int) or max_size <= 0:
            raise ValueError("max_size 必须是大于 0 的整数")

        self._template = client
        self._max_size = max_size
        self._clients = [client]
        self._available = [client]
        self._closed = False
        self._condition = threading.Condition(threading.RLock())

    @property
    def max_size(self) -> int:
        with self._condition:
            return self._max_size

    def ensure_capacity(self, max_size: int) -> None:
        """Increase the pool bound without eagerly opening connections."""

        if isinstance(max_size, bool) or not isinstance(max_size, int) or max_size <= 0:
            raise ValueError("max_size 必须是大于 0 的整数")
        with self._condition:
            if self._closed:
                raise RuntimeError("连接池已关闭")
            self._max_size = max(self._max_size, max_size)
            self._condition.notify_all()

    def _acquire(self) -> FailoverClient:
        with self._condition:
            while True:
                if self._closed:
                    raise RuntimeError("连接池已关闭")
                if self._available:
                    client = self._available.pop()
                    break
                if len(self._clients) < self._max_size:
                    client = self._template.fork()
                    self._clients.append(client)
                    break
                self._condition.wait()

        try:
            is_connected = getattr(client, "is_connected", None)
            if is_connected is False:
                client.connect()
        except Exception:
            self._release(client)
            raise

        with self._condition:
            closed = self._closed
        if closed:
            client.close()
            raise RuntimeError("连接池已关闭")
        return client

    def _release(self, client: FailoverClient) -> None:
        close_client = False
        with self._condition:
            if self._closed:
                close_client = True
            else:
                self._available.append(client)
                self._condition.notify()
        if close_client:
            client.close()

    @contextmanager
    def connection(self):
        """Borrow one exclusive client and always return it to the pool."""

        client = self._acquire()
        try:
            yield client
        finally:
            self._release(client)

    def close(self) -> None:
        """Close every pooled connection and wake blocked borrowers."""

        with self._condition:
            if self._closed:
                return
            self._closed = True
            clients = list(self._available)
            self._available.clear()
            self._condition.notify_all()

        # Borrowed clients are closed by _release() after their active call exits.
        for client in clients:
            with suppress(Exception):
                client.close()
