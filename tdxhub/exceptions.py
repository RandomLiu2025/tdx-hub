"""Public exception hierarchy used by tdxhub."""

from __future__ import annotations

from typing import Any


class TdxhubException(Exception):
    """Base class for all package-specific errors."""

    def __init__(
        self,
        message: str | None = None,
        *,
        provider: str | None = None,
        response: Any = None,
        data: Any = None,
    ) -> None:
        self.provider = provider
        self.response = response
        self.message = message or self.__class__.__name__
        self.data = data
        super().__init__(self.message)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.message}>"


class TdxhubValidationException(TdxhubException, ValueError):
    """Raised when a public API argument is invalid."""


class TdxhubConnectionError(TdxhubException, ConnectionError):
    """Raised when no configured quote endpoint can be reached."""


class TdxhubIncompleteDataError(TdxhubException):
    """Raised when a requested aggregate cannot be computed from complete data."""


class TdxhubModuleNotFoundError(TdxhubException, ModuleNotFoundError):
    """Raised when an optional integration dependency is unavailable."""


class FileNeedRefresh(FileNotFoundError):
    """Internal signal indicating that a cached file has expired."""
