"""FastAPI control plane for the live trading desk and review hub."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src import __version__
from src.dashboard.queries import TABLES, export_rows, hub_summary
from src.data.storage import session_scope
from src.pipeline import get_pipeline

STATIC_DIR = Path(__file__).resolve().parent / "static"


class SlackConnect(BaseModel):
    bot_token: str = ""
    webhook_url: str = ""
    channel: str = "forex"


class TradingToggle(BaseModel):
    enabled: bool = True


class SheetsConnect(BaseModel):
    composio_api_key: str = ""
    spreadsheet_id: str = ""
    connected_account_id: str = ""


class MT4Connect(BaseModel):
    login: str = ""
    password: str = ""
    server: str = ""
    metaapi_token: str = ""
    enabled: bool = True


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _table_filters(table: str, params: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "bars": ("symbol", "timeframe"),
        "indicators": ("symbol", "timeframe"),
        "signals": ("symbol", "action", "skipped", "source"),
        "setups": ("symbol", "side"),
        "trades": ("symbol", "side", "status"),
        "snapshots": (),
        "daily": (),
        "alerts": ("kind",),
        "cycles": (),
        "journal": ("symbol", "side", "outcome"),
        "lessons": ("symbol", "side", "rule"),
        "briefings": ("kind",),
    }
    keys = allowed.get(table, ())
    return {key: params[key] for key in keys if params.get(key) not in {None, "", "ALL", "all"}}


def create_app() -> FastAPI:
    app = FastAPI(title="Forex Sentinel", version=__version__)

    @app.get("/api/health")
    def health() -> dict:
        pipe = get_pipeline()
        from src.data.news import news_source_status
        from src.analysis.indicator_audit import read_status
        return {"indicator_audit": read_status(), "news_sources": news_source_status(), "version": __version__, "ok": True, "warm": pipe._warm, "trading": pipe.trading_enabled,
                "health_scope": "Service availability only; not strategy profitability or learning quality",
                "startup_tasks": getattr(pipe, "startup_tasks", {"state": "unknown"}),
                "documentation": getattr(pipe, "documentation_status", {"ok": False, "state": "pending"})}

    @app.get("/api/state")
    def state() -> dict:
        return get_pipeline().dashboard_state()

    @app.get("/api/chart")
    def chart(
        timeframe: str = Query(default="M5"),
        limit: int = Query(default=240, ge=50, le=500),
    ) -> dict:
        return get_pipeline().chart_pack(timeframe=timeframe, limit=limit)

    @app.get("/api/hub/summary")
    def summary() -> dict:
        with session_scope() as session:
            return hub_summary(session)

    @app.get("/api/tables/{table}")
    def table_rows(
        table: str,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=500),
        symbol: str | None = None,
        timeframe: str | None = None,
        action: str | None = None,
        skipped: str | None = None,
        source: str | None = None,
        side: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        outcome: str | None = None,
        rule: str | None = None,
    ) -> dict:
        if table not in TABLES:
            raise HTTPException(status_code=404, detail=f"unknown table {table}")
        filters = _table_filters(
            table,
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "action": action,
                "skipped": skipped,
                "source": source,
                "side": side,
                "status": status,
                "kind": kind,
                "outcome": outcome,
                "rule": rule,
            },
        )
        with session_scope() as session:
            return TABLES[table]["list"](session, page=page, page_size=page_size, **filters)

    @app.get("/api/tables/{table}/csv")
    def table_csv(
        table: str,
        symbol: str | None = None,
        timeframe: str | None = None,
        action: str | None = None,
        skipped: str | None = None,
        source: str | None = None,
        side: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        outcome: str | None = None,
        rule: str | None = None,
    ) -> StreamingResponse:
        if table not in TABLES:
            raise HTTPException(status_code=404, detail=f"unknown table {table}")
        filters = _table_filters(
            table,
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "action": action,
                "skipped": skipped,
                "source": source,
                "side": side,
                "status": status,
                "kind": kind,
                "outcome": outcome,
                "rule": rule,
            },
        )
        with session_scope() as session:
            headers, rows = export_rows(session, table, **filters)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(headers), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_cell(row.get(key)) for key in headers})
        payload = buf.getvalue()
        filename = TABLES[table]["filename"]
        return StreamingResponse(
            iter([payload]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/trading")
    def set_trading(payload: TradingToggle) -> dict:
        pipe = get_pipeline()
        try:
            pipe.set_trading(payload.enabled)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"trading_enabled": pipe.trading_enabled}

    @app.post("/api/cycle")
    def cycle() -> dict:
        return get_pipeline().run_cycle()

    @app.post("/api/briefing/morning")
    def briefing_morning(force: bool = Query(default=True)) -> dict:
        return get_pipeline().send_morning_brief(force=force)

    @app.post("/api/briefing/recap")
    def briefing_recap(force: bool = Query(default=True)) -> dict:
        return get_pipeline().send_night_recap(force=force)

    @app.post("/api/trades/{trade_id}/close")
    def close_trade(trade_id: int) -> dict:
        try:
            return get_pipeline().close_local_trade(trade_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/tape")
    def tape_pulse() -> dict:
        return get_pipeline().send_tape_pulse()

    @app.post("/api/intel")
    def intel_cycle() -> dict:
        return get_pipeline().run_intel(force_slack=True)

    @app.get("/api/playbook")
    def playbook() -> dict:
        return get_pipeline().playbook_payload()

    @app.get("/api/growth")
    def growth() -> dict:
        pipe = get_pipeline()
        if pipe._growth is None:
            study = pipe.refresh_growth()
        else:
            study = pipe._growth.as_dict()
            study["history"] = None if pipe._history is None else pipe._history.as_dict()
        payload = pipe.playbook_payload()
        return {
            "ok": True,
            "markdown": payload.get("growth") or "",
            "history_markdown": payload.get("history") or "",
            "study": study,
        }

    @app.post("/api/growth")
    def growth_restudy() -> dict:
        from src.analysis.growth import render_growth

        pipe = get_pipeline()
        study = pipe.refresh_growth()
        md = ""
        if pipe._growth is not None:
            md = render_growth(pipe._growth)
        return {"ok": True, "study": study, "markdown": md}

    @app.get("/api/history")
    def history() -> dict:
        from src.analysis.playbook import read_history

        pipe = get_pipeline()
        studying = bool(getattr(pipe, "_history_studying", False))
        if pipe._history is None:
            pipe.kick_history_study()
            studying = True
            study = None
        else:
            study = pipe._history.as_dict()
        payload = pipe.playbook_payload()
        markdown = payload.get("history") or read_history() or ""
        if studying and not markdown:
            markdown = "Historical study is running in the background so live quotes stay on the clock."
        return {
            "ok": True,
            "studying": studying,
            "markdown": markdown,
            "study": study,
        }

    @app.post("/api/history")
    def history_restudy() -> dict:
        from src.analysis.playbook import read_history
        from src.data.datasets import render_history

        pipe = get_pipeline()
        started = pipe.kick_history_study(force=True)
        md = ""
        study = None
        if pipe._history is not None:
            md = render_history(pipe._history)
            study = pipe._history.as_dict()
        elif not md:
            md = read_history() or "Historical study started in the background."
        return {
            "ok": True,
            "studying": True,
            "started": started,
            "study": study,
            "markdown": md,
        }

    @app.post("/api/slack/connect")
    def slack_connect(payload: SlackConnect) -> dict:
        try:
            return get_pipeline().connect_slack(
                bot_token=payload.bot_token,
                webhook_url=payload.webhook_url,
                channel=payload.channel or "forex",
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/sheets")
    def sheets_status() -> dict:
        return get_pipeline().sheets.status()

    @app.post("/api/sheets/sync")
    def sheets_sync() -> dict:
        pipe = get_pipeline()
        started = pipe.kick_sheets_sync()
        return {"ok": True, "started": started, **pipe.sheets.status()}

    @app.post("/api/sheets/connect")
    def sheets_connect(payload: SheetsConnect) -> dict:
        try:
            return get_pipeline().connect_sheets(
                composio_api_key=payload.composio_api_key,
                spreadsheet_id=payload.spreadsheet_id,
                connected_account_id=payload.connected_account_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/mt4")
    def mt4_status() -> dict:
        return get_pipeline().mt4.status().as_dict()

    @app.post("/api/mt4/connect")
    def mt4_connect(payload: MT4Connect) -> dict:
        try:
            return get_pipeline().connect_mt4(
                login=payload.login,
                password=payload.password,
                server=payload.server,
                metaapi_token=payload.metaapi_token,
                enabled=payload.enabled,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/mt4/bridge")
    def mt4_bridge_pull(
        secret: str = "",
        x_mt4_secret: str | None = Header(default=None, alias="X-MT4-Secret"),
    ) -> dict:
        token = secret or (x_mt4_secret or "")
        result = get_pipeline().mt4.pull_commands(secret=token)
        if not result.get("ok"):
            raise HTTPException(status_code=401, detail=result.get("error") or "bad bridge secret")
        return result

    @app.post("/api/mt4/bridge")
    def mt4_bridge_push(payload: dict[str, Any]) -> dict:
        result = get_pipeline().apply_mt4_bridge(payload)
        if not result.get("ok"):
            raise HTTPException(status_code=401, detail=result.get("error") or "bad bridge secret")
        return result

    @app.get("/api/news")
    def news_book() -> dict:
        from src.data.news import news_source_status
        from src.analysis.news_patterns import pattern_rows, recent_news
        from src.analysis.playbook import read_news, read_news_patterns

        pipe = get_pipeline()
        with session_scope() as session:
            items = recent_news(session, 60)
            patterns = pattern_rows(session)
        return {
            "ok": True,
            "items": items,
            "news_sources": news_source_status(),
            "patterns": patterns,
            "guide": read_news(),
            "patterns_markdown": read_news_patterns(),
            "bot": {
                "news_scan": f"{pipe.settings.news_scan_hour:02d}:{pipe.settings.news_scan_minute:02d} UTC daily",
            },
        }

    @app.post("/api/news/scan")
    def news_scan(force: bool = Query(default=True)) -> dict:
        try:
            return get_pipeline().run_news_scan(force=force, deep=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
