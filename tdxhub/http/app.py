"""Optional FastAPI application for tdxhub market-data services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .serialization import to_jsonable
from .service import MarketDataService


def create_app(service: MarketDataService) -> Any:
    """Create an HTTP application without requiring FastAPI for core imports."""
    try:
        from fastapi import FastAPI, Query, Request
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover - exercised without server extra
        raise RuntimeError(
            "HTTP server dependencies are not installed; install tdxhub[server]"
        ) from exc

    app = FastAPI(title="tdxhub HTTP API")

    def response(data: Any, *, status_code: int = 200) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"code": 0, "msg": "ok", "data": to_jsonable(data)},
        )

    def error(message: str, *, status_code: int) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"code": 1, "msg": message, "data": None},
        )

    def invoke(operation: Callable[..., Any], **kwargs: Any) -> JSONResponse:
        try:
            return response(operation(**kwargs))
        except LookupError as exc:
            return error(str(exc), status_code=404)
        except ValueError as exc:
            return error(str(exc), status_code=400)
        except Exception as exc:
            return error(str(exc), status_code=200)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = exc.errors()
        message = details[0].get("msg", "参数格式错误") if details else "参数格式错误"
        return error(str(message), status_code=400)

    @app.get("/")
    def health() -> JSONResponse:
        return response({"status": "running"})

    @app.get("/ready")
    def ready() -> JSONResponse:
        data = service.ready()
        if not data["standard"]:
            return error("标准行情连接未就绪", status_code=503)
        return response(data)

    @app.get("/count")
    def count(exchange: str) -> JSONResponse:
        return invoke(service.count, exchange=exchange)

    @app.get("/code/all")
    def code_all(exchange: str) -> JSONResponse:
        return invoke(service.code_all, exchange=exchange)

    @app.get("/code")
    def code(exchange: str, start: int = Query(ge=0, le=65535)) -> JSONResponse:
        return invoke(service.code, exchange=exchange, start=start)

    @app.get("/quote")
    def quote(codes: str) -> JSONResponse:
        return invoke(service.quote, codes=codes)

    @app.get("/stock/info")
    def stock_info(codes: str, refresh_industries: bool = False) -> JSONResponse:
        return invoke(
            service.stock_info,
            codes=codes,
            refresh_industries=refresh_industries,
        )

    @app.get("/call_auction")
    def call_auction(code: str) -> JSONResponse:
        return invoke(service.call_auction, code=code)

    @app.get("/gbbq")
    def gbbq(code: str) -> JSONResponse:
        return invoke(service.gbbq, code=code)

    @app.get("/finance")
    def finance(exchange: str, code: str) -> JSONResponse:
        return invoke(service.finance, exchange=exchange, code=code)

    @app.get("/company/category")
    def company_category(exchange: str, code: str) -> JSONResponse:
        return invoke(service.company_category, exchange=exchange, code=code)

    @app.get("/company/content")
    def company_content(
        exchange: str,
        code: str,
        filename: str,
        start: int = Query(ge=0, le=4294967295),
        length: int = Query(ge=0, le=4294967295),
    ) -> JSONResponse:
        return invoke(
            service.company_content,
            exchange=exchange,
            code=code,
            filename=filename,
            start=start,
            length=length,
        )

    @app.get("/tdx/stat")
    def statistics() -> JSONResponse:
        return invoke(service.statistics)

    @app.get("/tdx/stat2")
    def money_flow() -> JSONResponse:
        return invoke(service.money_flow)

    @app.get("/tdx/xgsg")
    def xgsg() -> JSONResponse:
        return invoke(service.xgsg)

    @app.get("/index")
    def index_kline(
        code: str,
        category: int = Query(alias="type", ge=0, le=255),
        start: int = Query(ge=0, le=65535),
        count: int = Query(ge=0, le=65535),
    ) -> JSONResponse:
        return invoke(
            service.index_kline,
            category=category,
            code=code,
            start=start,
            count=count,
        )

    @app.get("/index/all")
    def index_all(
        code: str,
        category: int = Query(alias="type", ge=0, le=255),
        since: str | None = None,
    ) -> JSONResponse:
        return invoke(service.index_all, category=category, code=code, since=since)

    @app.get("/kline")
    def kline(
        code: str,
        category: int = Query(alias="type", ge=0, le=255),
        start: int = Query(ge=0, le=65535),
        count: int = Query(ge=0, le=65535),
    ) -> JSONResponse:
        return invoke(service.kline, category=category, code=code, start=start, count=count)

    @app.get("/kline/all")
    def kline_all(
        code: str,
        category: int = Query(alias="type", ge=0, le=255),
        since: str | None = None,
    ) -> JSONResponse:
        return invoke(service.kline_all, category=category, code=code, since=since)

    def add_page_route(path: str, frequency: int, operation: Callable[..., Any]) -> None:
        def endpoint(
            code: str,
            start: int = Query(ge=0, le=65535),
            count: int = Query(ge=0, le=65535),
        ):
            return invoke(
                operation,
                category=frequency,
                code=code,
                start=start,
                count=count,
            )

        name = path.strip("/").replace("/", "_")
        endpoint.__name__ = name
        app.add_api_route(path, endpoint, methods=["GET"], name=name, operation_id=name)

    def add_all_route(path: str, frequency: int, operation: Callable[..., Any]) -> None:
        def endpoint(code: str):
            return invoke(operation, category=frequency, code=code)

        name = path.strip("/").replace("/", "_")
        endpoint.__name__ = name
        app.add_api_route(path, endpoint, methods=["GET"], name=name, operation_id=name)

    kline_periods = {
        "minute": 8,
        "5minute": 0,
        "15minute": 1,
        "30minute": 2,
        "60minute": 3,
        "day": 9,
        "week": 5,
        "month": 6,
        "quarter": 10,
        "year": 11,
    }
    for period, frequency in kline_periods.items():
        add_page_route(f"/kline/{period}", frequency, service.kline)
        if period != "day":
            add_all_route(f"/kline/{period}/all", frequency, service.kline_all)

    @app.get("/kline/minute/241")
    def kline_minute_241(code: str, since: str | None = None) -> JSONResponse:
        return invoke(service.minute_241, code=code, since=since)

    @app.get("/kline/day/all")
    def kline_day_all(
        code: str,
        since: str | None = None,
        adjust: str | None = None,
    ) -> JSONResponse:
        return invoke(
            service.kline_all,
            category=9,
            code=code,
            since=since,
            adjust=adjust,
        )

    index_page_periods = {
        "minute": 8,
        "5minute": 0,
        "15minute": 1,
        "30minute": 2,
        "60minute": 3,
        "day": 9,
    }
    for period, frequency in index_page_periods.items():
        add_page_route(f"/index/{period}", frequency, service.index_kline)

    index_all_periods = {
        "day": 9,
        "week": 5,
        "month": 6,
        "quarter": 10,
        "year": 11,
    }
    for period, frequency in index_all_periods.items():
        add_all_route(f"/index/{period}/all", frequency, service.index_all)

    @app.get("/minute")
    def minute(code: str) -> JSONResponse:
        return invoke(service.minute, code=code)

    @app.get("/minute/history")
    def history_minute(date: str, code: str) -> JSONResponse:
        return invoke(service.history_minute, date=date, code=code)

    @app.get("/trade")
    def trade(
        code: str,
        start: int = Query(ge=0, le=65535),
        count: int = Query(ge=0, le=65535),
    ) -> JSONResponse:
        return invoke(service.trade, code=code, start=start, count=count)

    @app.get("/trade/all")
    def trade_all(code: str) -> JSONResponse:
        return invoke(service.trade_all, code=code)

    @app.get("/trade/history")
    def history_trade(
        date: str,
        code: str,
        start: int = Query(ge=0, le=65535),
        count: int = Query(ge=0, le=65535),
    ) -> JSONResponse:
        return invoke(
            service.history_trade,
            date=date,
            code=code,
            start=start,
            count=count,
        )

    @app.get("/trade/history/day")
    def history_trade_day(date: str, code: str) -> JSONResponse:
        return invoke(service.history_trade_day, date=date, code=code)

    @app.get("/ex/markets")
    def ext_markets() -> JSONResponse:
        return invoke(service.ext_markets)

    @app.get("/ex/count")
    def ext_count() -> JSONResponse:
        return invoke(service.ext_count)

    @app.get("/ex/instruments")
    def ext_instruments(
        start: int = Query(ge=0, le=4294967295),
        count: int = Query(ge=0, le=65535),
    ) -> JSONResponse:
        return invoke(service.ext_instruments, start=start, count=count)

    @app.get("/ex/quote")
    def ext_quote(market: int = Query(ge=0, le=255), code: str = Query()) -> JSONResponse:
        return invoke(service.ext_quote, market=market, code=code)

    @app.get("/ex/quote_list")
    def ext_quote_list(
        market: int = Query(ge=0, le=255),
        category: int = Query(ge=0, le=255),
        start: int = Query(ge=0, le=65535),
        count: int = Query(ge=0, le=65535),
    ) -> JSONResponse:
        return invoke(
            service.ext_quote_list,
            market=market,
            category=category,
            start=start,
            count=count,
        )

    @app.get("/ex/bars")
    def ext_bars(
        category: int = Query(ge=0, le=255),
        market: int = Query(ge=0, le=255),
        code: str = Query(),
        start: int = Query(ge=0, le=65535),
        count: int = Query(ge=0, le=65535),
    ) -> JSONResponse:
        return invoke(
            service.ext_bars,
            category=category,
            market=market,
            code=code,
            start=start,
            count=count,
        )

    @app.get("/ex/minute")
    def ext_minute(market: int = Query(ge=0, le=255), code: str = Query()) -> JSONResponse:
        return invoke(service.ext_minute, market=market, code=code)

    @app.get("/ex/minute/hist")
    def ext_history_minute(
        market: int = Query(ge=0, le=255),
        code: str = Query(),
        date: int = Query(ge=0, le=4294967295),
    ) -> JSONResponse:
        return invoke(service.ext_history_minute, market=market, code=code, date=date)

    @app.get("/ex/trade")
    def ext_trade(
        market: int = Query(ge=0, le=255),
        code: str = Query(),
        start: int = Query(ge=0, le=65535),
        count: int = Query(ge=0, le=65535),
    ) -> JSONResponse:
        return invoke(
            service.ext_trade,
            market=market,
            code=code,
            start=start,
            count=count,
        )

    @app.get("/ex/trade/hist")
    def ext_history_trade(
        market: int = Query(ge=0, le=255),
        code: str = Query(),
        date: int = Query(ge=0, le=4294967295),
        start: int = Query(ge=0, le=65535),
        count: int = Query(ge=0, le=65535),
    ) -> JSONResponse:
        return invoke(
            service.ext_history_trade,
            market=market,
            code=code,
            date=date,
            start=start,
            count=count,
        )

    @app.get("/ex/bars/range")
    def ext_bars_range(
        market: int = Query(ge=0, le=255),
        code: str = Query(),
        date: int = Query(ge=0, le=4294967295),
        date2: int = Query(ge=0, le=4294967295),
    ) -> JSONResponse:
        return invoke(
            service.ext_bars_range,
            market=market,
            code=code,
            start_date=date,
            end_date=date2,
        )

    return app
