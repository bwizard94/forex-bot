from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.analysis.playbook import SHEETS_PATH, read_sheets
from src.config import Settings, reload_settings
from src.data.storage import init_db, insert_trade, reset_engine, session_scope
from src.notifications.sheets import (
    TAB_ORDER,
    SheetsPublisher,
    a1_range,
    build_workbook,
    parse_spreadsheet_id,
    persist_payload,
    publish_from_db,
)


def test_sheets_book_names_the_tabs() -> None:
    text = read_sheets()
    assert text
    assert SHEETS_PATH.name == "SHEETS.md"
    blob = text.lower()
    for tab in TAB_ORDER:
        assert tab.lower() in blob
    assert "composio" in blob
    assert "eur/usd" in blob


def test_a1_range_quotes_tabs_and_spans_columns() -> None:
    assert a1_range("Overview", 3, 2) == "'Overview'!A1:B3"
    assert a1_range("DailyPnL", 1, 27) == "'DailyPnL'!A1:AA1"
    assert a1_range("O'Brien", 2, 1) == "'O''Brien'!A1:A2"


def test_parse_spreadsheet_id_from_url_or_raw() -> None:
    sid = "1AbC_def-123"
    assert parse_spreadsheet_id(sid) == sid
    assert (
        parse_spreadsheet_id(f"https://docs.google.com/spreadsheets/d/{sid}/edit#gid=0")
        == sid
    )
    assert parse_spreadsheet_id("") == ""


def test_build_workbook_includes_trades_and_empty_tabs(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "sheets.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    reset_engine()
    reload_settings()
    init_db()
    opened = datetime(2026, 9, 19, 4, 0, tzinfo=timezone.utc)
    with session_scope() as session:
        insert_trade(
            session,
            {
                "symbol": "EUR/USD",
                "side": "SELL",
                "units": 100000,
                "requested_entry": 1.1487,
                "fill_price": 1.14871,
                "stop_loss": 1.1493,
                "take_profit_1": 1.1482,
                "take_profit_2": 1.1477,
                "broker_take_profit": 1.1477,
                "status": "open",
                "remaining_units": 100000,
                "source": "bot",
                "opened_at": opened,
                "broker_trade_id": "120",
            },
        )
        book = build_workbook(session)
    assert tuple(book.keys()) == TAB_ORDER
    trades = book["Trades"]
    assert trades[0][0] == "id"
    assert any(row[3] == "EUR/USD" and row[4] == "SELL" for row in trades[1:])
    open_tab = book["Open"]
    assert any(row[3] == "SELL" and row[-1] == "120" for row in open_tab[1:])
    overview = {row[0]: row[1] for row in book["Overview"][1:]}
    assert overview["Open tickets"] == 1
    assert overview["Desk"] == "Forex Sentinel — EUR/USD specialist"


def test_push_book_packs_locally_without_composio_key(tmp_path: Path, monkeypatch) -> None:
    payload = tmp_path / "payload.json"
    monkeypatch.setenv("COMPOSIO_API_KEY", "")
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
    reload_settings()
    publisher = SheetsPublisher(Settings())
    book = {"Overview": [["Field", "Value"], ["Desk", "EUR/USD"]]}
    result = publisher.push_book(book, payload_path=payload)
    assert result.ok is False
    assert "Packed locally" in result.reason
    assert payload.exists()
    raw = payload.read_text(encoding="utf-8")
    assert "Overview" in raw
    assert "EUR/USD" in raw


def test_push_book_creates_and_writes_tabs_through_injected_execute(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple[str, dict]] = []

    def execute(slug: str, arguments: dict) -> dict:
        calls.append((slug, arguments))
        if slug == "GOOGLESHEETS_CREATE_GOOGLE_SHEET1":
            return {
                "spreadsheetId": "sheet-abc",
                "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/sheet-abc/edit",
            }
        if slug == "GOOGLESHEETS_GET_SHEET_NAMES":
            return {"sheet_names": ["Sheet1"]}
        return {"ok": True}

    settings = Settings(composio_api_key="ak_test")
    monkeypatch.setattr("src.notifications.sheets.upsert_env_values", lambda updates, path=".env": None)
    monkeypatch.setattr("src.notifications.sheets.reload_settings", lambda: settings)
    publisher = SheetsPublisher(settings, execute=execute)
    book = {
        "Overview": [["Field", "Value"], ["Desk", "EUR/USD"]],
        "Trades": [["id", "side"], [1, "SELL"]],
    }
    result = publisher.push_book(book, payload_path=tmp_path / "payload.json")
    assert result.ok
    assert result.spreadsheet_id == "sheet-abc"
    slugs = [slug for slug, _ in calls]
    assert "GOOGLESHEETS_CREATE_GOOGLE_SHEET1" in slugs
    assert slugs.count("GOOGLESHEETS_ADD_SHEET") >= 1
    assert "GOOGLESHEETS_VALUES_UPDATE" in slugs
    written_tabs = [args["range"] for slug, args in calls if slug == "GOOGLESHEETS_VALUES_UPDATE"]
    assert any("Sheet1" in rng for rng in written_tabs)
    assert any("Trades" in rng for rng in written_tabs)


def test_persist_payload_roundtrip(tmp_path: Path) -> None:
    path = persist_payload({"Open": [["id"], [12]]}, path=tmp_path / "book.json")
    assert path.exists()
    assert "Open" in path.read_text(encoding="utf-8")


def test_publish_from_db_uses_injected_publisher(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "sheets.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    reset_engine()
    reload_settings()
    init_db()
    seen: list[dict] = []

    class Stub(SheetsPublisher):
        def push_book(self, book, *, payload_path=None):  # noqa: ANN001
            seen.append(book)
            from src.notifications.sheets import SheetsPush

            return SheetsPush(True, "stub", tabs=list(book.keys()))

    result = publish_from_db(publisher=Stub(Settings()))
    assert result.ok
    assert seen and tuple(seen[0].keys()) == TAB_ORDER
