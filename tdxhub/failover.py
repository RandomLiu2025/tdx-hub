"""Single-connection runtime failover for TDX quote clients."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterable
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from functools import wraps
from typing import Any

from tdxhub.tdx.deadline import LockTimeout, deadline_lock, remaining, request_budget
from tdxhub.tdx.errors import (
    ProtocolError,
    ResponseHeaderRecvFails,
    ResponseRecvFails,
    SendRequestPkgFails,
    TdxConnectionError,
    TdxFunctionCallError,
)

Endpoint = tuple[str, int]
_RETRYABLE_ERRORS = (OSError, TdxConnectionError, TdxFunctionCallError)

Capability = tuple[str, tuple[int, ...], int | None]


def request_capability(name: str, args: tuple, kwargs: dict) -> Capability | None:
    """Use only validated, bounded market/interface keys, never security codes."""

    def argument(index, key):
        return args[index] if len(args) > index else kwargs.get(key)

    if name in {"get_security_bars", "get_index_bars"}:
        category, market = argument(0, "category"), argument(1, "market")
        if market in (0, 1, 2) and isinstance(category, int) and 0 <= category <= 11:
            return name, (market,), category
    elif name == "get_security_quotes":
        stocks = argument(0, "all_stock")
        if (
            isinstance(stocks, (list, tuple))
            and stocks
            and all(isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[0], int) for item in stocks)
        ):
            markets = tuple(sorted({item[0] for item in stocks}))
            if all(market in (0, 1, 2) for market in markets):
                return name, markets, None
    return None


def _is_protocol_error(error: BaseException) -> bool:
    # EOF / send failures are transport-wide, not evidence of unsupported interfaces.
    original = getattr(error, "original_exception", None) or error
    return isinstance(original, ProtocolError) and not isinstance(
        original, (ResponseHeaderRecvFails, ResponseRecvFails, SendRequestPkgFails)
    )


@dataclass
class _CapabilityState:
    status: str
    expires_at: float
    last_error: str | None = None


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
        capability_ttl: float = 300.0,
    ) -> None:
        if cooldown < 0:
            raise ValueError("cooldown 必须大于等于 0")

        if capability_ttl < 0:
            raise ValueError("capability_ttl 必须大于等于 0")
        self.capability_ttl = float(capability_ttl)
        self._capabilities: dict[tuple[Endpoint, Capability], _CapabilityState] = {}
        self.cooldown = float(cooldown)
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._states: dict[Endpoint, _EndpointState] = {}
        for address, port in endpoints:
            endpoint = (str(address), int(port))
            self._states.setdefault(endpoint, _EndpointState(endpoint))

    def _prune_capabilities(self) -> None:
        now = self._clock()
        self._capabilities = {key: state for key, state in self._capabilities.items() if state.expires_at > now}

    def capability_status(self, endpoint: Endpoint, capability: Capability | None) -> str:
        with self._lock:
            self._prune_capabilities()
            state = self._capabilities.get((endpoint, capability))
            return state.status if state else "unknown"

    def report_capability(
        self, endpoint: Endpoint, capability: Capability, status: str, error: str | None = None
    ) -> None:
        if status not in {"supported", "unknown", "failed"}:
            raise ValueError("invalid capability status")
        with self._lock:
            self._prune_capabilities()
            self._capabilities[endpoint, capability] = _CapabilityState(
                status, self._clock() + self.capability_ttl, error
            )

    def available(self, capability: Capability | None = None) -> list[Endpoint]:
        """Prefer demonstrated support; failures expire and never imply permanent exclusion."""
        now = self._clock()
        with self._lock:
            self._prune_capabilities()
            endpoints = [state.endpoint for state in self._states.values() if state.cooldown_until <= now]
            if capability is None:
                return endpoints
            endpoints = [ep for ep in endpoints if self.capability_status(ep, capability) != "failed"]
            return sorted(endpoints, key=lambda ep: self.capability_status(ep, capability) != "supported")

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
            self._prune_capabilities()
            return [
                {
                    **(
                        {
                            "capabilities": [
                                {
                                    "interface": key[0],
                                    "markets": list(key[1]),
                                    "category": key[2],
                                    "status": cap.status,
                                    "ttl_remaining": max(0.0, cap.expires_at - now),
                                    "last_error": cap.last_error,
                                }
                                for (ep, key), cap in self._capabilities.items()
                                if ep == state.endpoint
                            ]
                        }
                        if any(ep == state.endpoint for ep, _ in self._capabilities)
                        else {}
                    ),
                    "server": state.endpoint,
                    "active": state.endpoint == current,
                    "failures": state.failures,
                    "cooldown_remaining": max(0.0, state.cooldown_until - now),
                    "last_error": state.last_error,
                }
                for state in self._states.values()
            ]


def _bounded_request(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        try:
            with request_budget(self.request_timeout, self._clock), deadline_lock(self._lock):
                return method(self, *args, **kwargs)
        except TimeoutError:
            if self.raise_exception:
                raise
            return False if method.__name__ == "connect" else None

    return call


class FailoverClient:
    """Proxy one active TDX client and fail over on transport/protocol errors."""

    def __init__(
        self,
        endpoint_pool: EndpointPool,
        client_factory: Callable[[], Any],
        *,
        timeout: float = 3,
        request_timeout: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_failovers: int = 2,
        raise_exception: bool = True,
        on_switch: Callable[[Endpoint], None] | None = None,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if max_failovers < 0:
            raise ValueError("max_failovers 必须大于等于 0")

        request_timeout = timeout if request_timeout is None else request_timeout
        if not math.isfinite(request_timeout) or request_timeout <= 0:
            raise ValueError("request_timeout 必须是大于 0 的有限数字")
        self.request_timeout = request_timeout
        self._clock = clock
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
            # A broken transport may make client.disconnect() fail as well.
            with suppress(Exception):
                client.close()

    def _connect_endpoint(self, endpoint: Endpoint) -> bool:
        remaining()
        client = self.client_factory()
        # The proxy owns retries; the raw client must fail on its first error.
        client.auto_retry = False
        client.raise_exception = True
        client.heartbeat_runner = lambda: self._run_heartbeat(client)
        client.heartbeat_error_callback = lambda error: self._heartbeat_failed(client, endpoint, error)
        try:
            connected = client.connect(*endpoint, time_out=self.timeout)
            remaining()
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

    @_bounded_request
    def connect(self) -> bool:
        """Connect to the first currently available endpoint."""

        with self._lock:
            if self._connected:
                return True

            last_error: BaseException | None = None
            endpoints = self.endpoint_pool.available()[: self.max_failovers + 1]
            for endpoint in endpoints:
                remaining()
                try:
                    return self._connect_endpoint(endpoint)
                except _RETRYABLE_ERRORS as exc:
                    self.endpoint_pool.report_failure(endpoint, exc)
                    last_error = exc
                    self._last_error = exc

            remaining()
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
            request_timeout=self.request_timeout,
            clock=self._clock,
            max_failovers=self.max_failovers,
            raise_exception=self.raise_exception,
            on_switch=self.on_switch,
        )

    def server_status(self) -> list[dict[str, Any]]:
        current = self.endpoint if self._connected else None
        return self.endpoint_pool.snapshot(current=current)

    def _heartbeat_failed(self, client, endpoint, error):
        original = getattr(error, "original_exception", None) or error
        if isinstance(original, LockTimeout):
            return
        with self._lock:
            if not self._connected or self._client is not client:
                return
            self.endpoint_pool.report_failure(endpoint, error)
            self._last_error = error
            self._close_current()

    def _run_heartbeat(self, client):
        try:
            with request_budget(self.request_timeout, self._clock), deadline_lock(self._lock):
                if not self._connected or self._client is not client:
                    return
                try:
                    result = client.do_heartbeat()
                    remaining()
                    return result
                except Exception as exc:
                    original = getattr(exc, "original_exception", None) or exc
                    if isinstance(original, LockTimeout):
                        if original is exc:
                            raise
                        raise original from exc
                    self._heartbeat_failed(client, self.endpoint, exc)
                    raise
        except LockTimeout:
            # Busy foreground calls are not failed heartbeats; try again next interval.
            return

    @_bounded_request
    def _invoke(self, name: str, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            capability = request_capability(name, args, kwargs)
            candidates = self.endpoint_pool.available(capability)
            # Retain the active socket unless another server has stronger evidence.
            if (
                self._connected
                and self.endpoint in candidates
                and (
                    capability is None
                    or self.endpoint_pool.capability_status(self.endpoint, capability)
                    == self.endpoint_pool.capability_status(candidates[0], capability)
                )
            ):
                candidates.remove(self.endpoint)
                candidates.insert(0, self.endpoint)
            last_error = self._last_error
            for endpoint in candidates[: self.max_failovers + 1]:
                remaining()
                if not self._connected or self.endpoint != endpoint:
                    self._close_current()
                    try:
                        self._connect_endpoint(endpoint)
                    except _RETRYABLE_ERRORS as exc:
                        self.endpoint_pool.report_failure(endpoint, exc)
                        last_error = self._last_error = exc
                        continue
                method = getattr(self._client, name)
                try:
                    result = method(*args, **kwargs)
                    remaining()
                except _RETRYABLE_ERRORS as exc:
                    original = getattr(exc, "original_exception", None) or exc
                    if isinstance(original, LockTimeout):
                        if original is exc:
                            raise
                        raise original from exc
                    if capability is not None and _is_protocol_error(exc):
                        self.endpoint_pool.report_capability(endpoint, capability, "failed", str(exc))
                    else:
                        self.endpoint_pool.report_failure(endpoint, exc)
                    self._close_current()
                    last_error = self._last_error = exc
                else:
                    self.endpoint_pool.report_success(endpoint)
                    if capability is not None:
                        self.endpoint_pool.report_capability(endpoint, capability, "supported" if result else "unknown")
                    self._last_error = None
                    return result
            remaining()
            if self.raise_exception:
                raise last_error or TdxConnectionError(f"当前没有可用的行情服务器 capability={capability}")
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
