"""HTTP service adapters and optional FastAPI application factory."""

from .app import create_app
from .service import MarketDataService

__all__ = ["MarketDataService", "create_app"]
