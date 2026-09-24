"""Per-call monotonic I/O budgets, propagated without changing protocol APIs."""

import time
from contextlib import contextmanager
from contextvars import ContextVar

_current = ContextVar("tdx_request_deadline", default=None)


class LockTimeout(TimeoutError):
    """Local contention is not evidence that a remote endpoint is unhealthy."""


def remaining():
    state = _current.get()
    if state is None:
        return None
    end, clock = state
    value = end - clock()
    if value <= 0:
        raise TimeoutError("TDX request deadline exceeded")
    return value


@contextmanager
def request_budget(seconds, clock=time.monotonic):
    outer = remaining()
    seconds = seconds if outer is None else min(seconds, outer)
    token = _current.set((clock() + seconds, clock))
    try:
        yield
        remaining()
    finally:
        _current.reset(token)


@contextmanager
def deadline_lock(lock):
    if lock is None:
        yield
        return
    try:
        seconds = remaining()
    except TimeoutError as exc:
        raise LockTimeout("TDX request deadline exceeded before lock") from exc
    acquired = lock.acquire() if seconds is None else lock.acquire(timeout=seconds)
    if not acquired:
        raise LockTimeout("TDX request deadline exceeded waiting for lock")
    try:
        try:
            remaining()
        except TimeoutError as exc:
            raise LockTimeout("TDX request deadline exceeded waiting for lock") from exc
        yield
    finally:
        lock.release()


@contextmanager
def socket_budget(sock):
    """Cap each blocking operation and restore the original per-I/O timeout."""
    seconds = remaining()
    adjustable = seconds is not None and hasattr(sock, "gettimeout") and hasattr(sock, "settimeout")
    timeout = sock.gettimeout() if adjustable else None
    if adjustable:
        sock.settimeout(seconds if timeout is None else min(timeout, seconds))
    try:
        yield
        remaining()
    finally:
        if adjustable:
            sock.settimeout(timeout)
