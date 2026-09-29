"""Google Sheets book of the EUR/USD desk.

Builds a multi-tab workbook from SQLite (trades, journals, P/L, lessons,
account snapshots, live signals) and publishes it through Composio's
Google Sheets tools when ``COMPOSIO_API_KEY`` is set.

Without a key the payload is still packed and stored locally so the next
connected push is complete.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests
from loguru import logger

from src import __version__
from src.config import Settings, get_settings, reload_settings, upsert_env_values
from src.analysis.news_patterns import pattern_rows
from src.dashboard.queries import (
    hub_summary,
    list_daily_pnl,
    list_journals,
    list_lessons,
    list_news,
    list_signals,
    list_snapshots,
    list_trades,
)
from src.data.storage import get_open_trades, latest_snapshot, session_scope
from src.utils import utcnow

TAB_ORDER = (
    "Overview",
    "Trades",
    "Journal",
    "DailyPnL",
    "Lessons",
    "Account",
    "Signals",
    "Open",
    "News",
    "NewsPatterns",
)

PAYLOAD_PATH = Path("data/sheets_payload.json")
COMPOSIO_EXECUTE = "https://backend.composio.dev/api/v3/tools/execute/{slug}"


def _cell(value: Any) -> str | int | float | bool:
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item not in (None, ""))
    text = str(value)
    if len(text) > 49000:
        return text[:49000]
    return text


def _rows(headers: list[str], records: list[dict[str, Any]]) -> list[list[Any]]:
    out: list[list[Any]] = [headers]
    for rec in records:
        out.append([_cell(rec.get(key)) for key in headers])
    if len(out) == 1:
        out.append([""] * len(headers))
    return out


def parse_spreadsheet_id(value: str) -> str:
    """Accept a raw spreadsheet id or a docs.google.com URL."""
    text = (value or "").strip()
    if not text:
        return ""
    if "/d/" in text:
        after = text.split("/d/", 1)[1]
        return after.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    return text


def a1_range(tab: str, rows: int, cols: int) -> str:
    """Quoted A1 range covering the matrix (1-indexed, inclusive)."""
    last_col = _col_letter(max(1, cols))
    last_row = max(1, rows)
    safe = tab.replace("'", "''")
    return f"'{safe}'!A1:{last_col}{last_row}"


def _col_letter(n: int) -> str:
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters or "A"


def build_workbook(
    session,
    *,
    settings: Settings | None = None,
    account: Any | None = None,
) -> dict[str, list[list[Any]]]:
    """Return tab name → 2D values, headers on row 1."""
    settings = settings or get_settings()
    summary = hub_summary(session)
    counts = summary.get("counts") or {}
    snap = latest_snapshot(session)
    nav = getattr(account, "nav", None)
    balance = getattr(account, "balance", None)
    unreal = getattr(account, "unrealized_pl", None)
    if nav is None and snap is not None:
        nav = float(snap.nav)
        balance = float(snap.balance)
        unreal = float(snap.unrealized_pl)

    trades = list_trades(session, page_size=2000)["rows"]
    journals = list_journals(session, page_size=2000)["rows"]
    daily = list_daily_pnl(session, page_size=500)["rows"]
    lessons = list_lessons(session, page_size=500)["rows"]
    snaps = list_snapshots(session, page_size=400)["rows"]
    signals = list_signals(session, source="live", page_size=400)["rows"]
    open_rows = [
        {
            "id": t.id,
            "opened_at": t.opened_at.isoformat() if t.opened_at else "",
            "symbol": t.symbol,
            "side": t.side,
            "source": getattr(t, "source", None) or "bot",
            "venue": getattr(t, "venue", None) or "oanda",
            "status": t.status,
            "units": t.units,
            "remaining_units": t.remaining_units,
            "fill_price": t.fill_price,
            "stop_loss": t.stop_loss,
            "take_profit_1": t.take_profit_1,
            "take_profit_2": t.take_profit_2,
            "slippage_pips": t.slippage_pips,
            "broker_trade_id": t.broker_trade_id,
        }
        for t in get_open_trades(session)
    ]

    overview = [
        ["Field", "Value"],
        ["Updated (UTC)", utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")],
        ["Desk", "Forex Sentinel — EUR/USD specialist"],
        ["Version", __version__],
        ["Spreadsheet ID", settings.google_sheets_spreadsheet_id or "(creating on first push)"],
        ["NAV", nav if nav is not None else ""],
        ["Balance", balance if balance is not None else ""],
        ["Unrealized P/L", unreal if unreal is not None else ""],
        ["Book realized P/L", summary.get("realized_pl")],
        ["Open tickets", counts.get("open_trades")],
        ["Closed tickets", counts.get("closed_trades")],
        ["All tickets", counts.get("trades")],
        ["Journals", counts.get("journals")],
        ["Journal losses", counts.get("journal_losses")],
        ["Active lessons", counts.get("active_lessons")],
        ["Live signals stored", counts.get("signals")],
        ["News headlines logged", counts.get("news_items")],
        ["News waiting on tape check", counts.get("news_pending")],
        ["Note", "Rewritten on every fill, close, and intel cycle. Do not edit these tabs — the desk overwrites them."],
    ]

    return {
        "Overview": overview,
        "Trades": _rows(
            [
                "id",
                "opened_at",
                "closed_at",
                "symbol",
                "side",
                "source",
                "venue",
                "status",
                "units",
                "remaining_units",
                "requested_entry",
                "fill_price",
                "slippage_pips",
                "stop_loss",
                "take_profit_1",
                "take_profit_2",
                "exit_price",
                "realized_pl",
                "close_reason",
                "broker_trade_id",
                "signal_id",
                "error_message",
            ],
            trades,
        ),
        "Journal": _rows(
            [
                "trade_id",
                "updated_at",
                "symbol",
                "side",
                "outcome",
                "realized_pl",
                "hold_minutes",
                "fingerprint",
                "rsi_bucket",
                "bb_zone",
                "htf_bias",
                "close_reason",
                "mistakes",
                "entry_thesis",
                "what_went_wrong",
                "how_to_avoid",
                "what_went_right",
                "lesson",
            ],
            journals,
        ),
        "DailyPnL": _rows(
            [
                "day",
                "starting_balance",
                "realized_pl",
                "trades_opened",
                "trades_closed",
                "halted",
                "halt_reason",
            ],
            daily,
        ),
        "Lessons": _rows(
            [
                "fingerprint",
                "symbol",
                "side",
                "action",
                "min_strength",
                "skip_until",
                "win_count",
                "loss_count",
                "scratch_count",
                "net_pl",
                "last_outcome",
                "active",
                "lesson",
            ],
            lessons,
        ),
        "Account": _rows(
            [
                "ts",
                "nav",
                "balance",
                "unrealized_pl",
                "realized_pl",
                "margin_used",
                "margin_available",
                "open_trade_count",
                "peak_nav",
                "drawdown_pct",
            ],
            snaps,
        ),
        "Signals": _rows(
            [
                "ts",
                "symbol",
                "action",
                "price",
                "strength",
                "skipped",
                "skip_reason",
                "signal_type",
                "fingerprint",
                "htf_bias",
                "d1_bias",
                "rsi",
                "reason",
            ],
            signals,
        ),
        "Open": _rows(
            [
                "id",
                "opened_at",
                "symbol",
                "side",
                "source",
                "venue",
                "status",
                "units",
                "remaining_units",
                "fill_price",
                "stop_loss",
                "take_profit_1",
                "take_profit_2",
                "slippage_pips",
                "broker_trade_id",
            ],
            open_rows,
        ),
        "News": _rows(
            [
                "ts",
                "published",
                "source",
                "category",
                "predicted",
                "verdict",
                "title",
                "price_at",
                "move_1h_pips",
                "url",
            ],
            list_news(session, page_size=1500)["rows"],
        ),
        "NewsPatterns": _rows(
            [
                "category",
                "samples",
                "correct",
                "wrong",
                "unclear",
                "pending",
                "hit_rate",
                "avg_abs_1h_pips",
                "reaction",
            ],
            pattern_rows(session),
        ),
    }


def persist_payload(book: dict[str, list[list[Any]]], path: Path = PAYLOAD_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {name: [[_cell(c) for c in row] for row in rows] for name, rows in book.items()}
    path.write_text(json.dumps({"ts": utcnow().isoformat(), "tabs": serializable}, indent=2), encoding="utf-8")
    return path


@dataclass
class SheetsPush:
    ok: bool
    reason: str
    spreadsheet_id: str = ""
    spreadsheet_url: str = ""
    tabs: list[str] = field(default_factory=list)


class SheetsPublisher:
    """Pushes the packed book through Composio Google Sheets tools."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        execute: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._execute = execute
        self._lock = threading.Lock()
        self.last: SheetsPush | None = None

    def status(self) -> dict[str, Any]:
        sid = (self.settings.google_sheets_spreadsheet_id or "").strip()
        url = (self.settings.google_sheets_spreadsheet_url or "").strip()
        if sid and not url:
            url = f"https://docs.google.com/spreadsheets/d/{sid}/edit"
        key = self.settings.composio_api_key.get_secret_value()
        return {
            "configured": bool(key),
            "spreadsheet_id": sid,
            "spreadsheet_url": url,
            "last": None
            if self.last is None
            else {
                "ok": self.last.ok,
                "reason": self.last.reason,
                "tabs": self.last.tabs,
            },
        }

    def execute(self, slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._execute is not None:
            return self._execute(slug, arguments)
        key = self.settings.composio_api_key.get_secret_value().strip()
        if not key:
            raise RuntimeError("COMPOSIO_API_KEY is not set")
        payload: dict[str, Any] = {"arguments": arguments, "allow_tracing": False}
        account = (self.settings.composio_connected_account_id or "").strip()
        if account:
            payload["connected_account_id"] = account
        response = requests.post(
            COMPOSIO_EXECUTE.format(slug=slug),
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        body = response.json()
        if isinstance(body, dict) and body.get("successful") is False:
            raise RuntimeError(str(body.get("error") or body.get("message") or "Composio execute failed"))
        return body.get("data") if isinstance(body, dict) else body

    def ensure_spreadsheet(self, title: str = "Forex Sentinel — EUR/USD book") -> str:
        sid = (self.settings.google_sheets_spreadsheet_id or "").strip()
        if sid:
            return sid
        created = self.execute("GOOGLESHEETS_CREATE_GOOGLE_SHEET1", {"title": title})
        data = created if isinstance(created, dict) else {}
        nested = data.get("data") if isinstance(data.get("data"), dict) else data
        sid = str(
            nested.get("spreadsheetId")
            or nested.get("spreadsheet_id")
            or nested.get("id")
            or ""
        )
        url = str(nested.get("spreadsheetUrl") or nested.get("spreadsheet_url") or "")
        if not sid:
            raise RuntimeError(f"Create spreadsheet returned no id: {created}")
        if not url:
            url = f"https://docs.google.com/spreadsheets/d/{sid}/edit"
        upsert_env_values(
            {
                "GOOGLE_SHEETS_SPREADSHEET_ID": sid,
                "GOOGLE_SHEETS_SPREADSHEET_URL": url,
            }
        )
        self.settings = reload_settings()
        return sid

    def _ensure_tabs(self, spreadsheet_id: str, tabs: list[str]) -> list[str]:
        names: list[str] = []
        try:
            info = self.execute("GOOGLESHEETS_GET_SHEET_NAMES", {"spreadsheet_id": spreadsheet_id})
            payload = info if isinstance(info, dict) else {}
            raw = payload.get("sheets") or payload.get("sheet_names") or payload.get("data") or payload
            if isinstance(raw, dict):
                raw = raw.get("sheets") or raw.get("sheet_names") or raw.get("names") or []
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, str):
                        names.append(item)
                    elif isinstance(item, dict):
                        title = item.get("title") or item.get("name")
                        if title:
                            names.append(str(title))
        except Exception:
            logger.exception("Could not list Google Sheet tabs")
        existing = {n.lower() for n in names}
        if "overview" not in existing and "sheet1" in existing:
            existing.add("overview")
        for tab in tabs:
            if tab.lower() in existing:
                continue
            self.execute(
                "GOOGLESHEETS_ADD_SHEET",
                {
                    "spreadsheet_id": spreadsheet_id,
                    "title": tab,
                    "properties": {
                        "gridProperties": {"rowCount": 2000, "columnCount": 30, "frozenRowCount": 1}
                    },
                },
            )
            names.append(tab)
            existing.add(tab.lower())
        return names

    def _write_tab_name(self, tab: str, existing_names: list[str]) -> str:
        lower = {n.lower(): n for n in existing_names}
        if tab == "Overview" and "sheet1" in lower:
            return lower["sheet1"]
        if tab.lower() in lower:
            return lower[tab.lower()]
        return tab

    def push_book(
        self,
        book: dict[str, list[list[Any]]],
        *,
        payload_path: Path | None = None,
    ) -> SheetsPush:
        persist_payload(book, path=payload_path or PAYLOAD_PATH)
        key = self.settings.composio_api_key.get_secret_value().strip()
        if not key and self._execute is None:
            result = SheetsPush(
                False,
                "Packed locally. Connect Google Sheets (Composio) and set COMPOSIO_API_KEY to push.",
            )
            self.last = result
            return result
        try:
            sid = self.ensure_spreadsheet()
            names = self._ensure_tabs(sid, list(book.keys())) or []
            written: list[str] = []
            for tab, rows in book.items():
                target = self._write_tab_name(tab, names)
                rng = a1_range(target, len(rows), max(len(r) for r in rows))
                self.execute(
                    "GOOGLESHEETS_VALUES_UPDATE",
                    {
                        "spreadsheet_id": sid,
                        "range": rng,
                        "values": rows,
                        "value_input_option": "USER_ENTERED",
                        "auto_expand_sheet": True,
                    },
                )
                written.append(tab)
            url = (
                self.settings.google_sheets_spreadsheet_url
                or f"https://docs.google.com/spreadsheets/d/{sid}/edit"
            )
            result = SheetsPush(True, f"Wrote {len(written)} tabs", sid, url, written)
            self.last = result
            logger.info("Google Sheets book updated {} tabs → {}", len(written), url)
            return result
        except Exception as exc:
            logger.exception("Google Sheets push failed")
            result = SheetsPush(False, str(exc)[:400])
            self.last = result
            return result


def publish_from_db(
    *,
    settings: Settings | None = None,
    account: Any | None = None,
    publisher: SheetsPublisher | None = None,
) -> SheetsPush:
    settings = settings or get_settings()
    publisher = publisher or SheetsPublisher(settings)
    with session_scope() as session:
        book = build_workbook(session, settings=settings, account=account)
    return publisher.push_book(book)
