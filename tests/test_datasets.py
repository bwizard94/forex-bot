from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.analysis.growth import growth_gate
from src.analysis.signals import TradeSignal
from src.config import Settings
from src.data.datasets import (
    classify_ohlc,
    clear_history_cache,
    dataset_dirs,
    desktop_dataset_dirs,
    infer_timeframe,
    persist_history_book,
    render_history,
    study_extra_datasets,
    write_history,
)
from src.utils import utcnow


def _signal(**overrides) -> TradeSignal:
    base = dict(
        symbol="EUR/USD",
        timeframe="M5",
        action="BUY",
        timestamp=datetime.now(timezone.utc),
        price=1.14659,
        entry=1.14659,
        stop_loss=1.14590,
        take_profit_1=1.14740,
        take_profit_2=1.14820,
        risk_reward=1.33,
        atr=0.00034,
        rsi=32.0,
        ema_fast=1.14710,
        ema_slow=1.14680,
        bb_upper=1.14690,
        bb_mid=1.14580,
        bb_lower=1.14470,
        htf_bias="bullish",
        d1_bias="bullish",
        confluence=["RSI oversold"],
        reason="RSI oversold",
        strength=50,
    )
    base.update(overrides)
    return TradeSignal(**base)  # type: ignore[arg-type]


def _write_eurusd_csv(path: Path, n: int = 240) -> None:
    rng = pd.date_range("2024-03-04 00:00", periods=n, freq="5min", tz="UTC")
    price = 1.09000
    rows = ["datetime,open,high,low,close,volume"]
    for i, ts in enumerate(rng):
        # Slow downtrend with periodic pops so RSI can stretch and EMA stays stacked.
        price -= 0.00004
        if i % 17 == 0:
            price += 0.00055
        noise = ((i % 7) - 3) * 0.00003
        o = price
        h = o + abs(noise) + 0.00012
        l = o - abs(noise) - 0.00012
        c = o + noise
        price = c
        rows.append(f"{ts.isoformat()},{o:.5f},{h:.5f},{l:.5f},{c:.5f},120")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_empty_extra_datasets_folder(tmp_path: Path) -> None:
    folder = tmp_path / "extra datasets"
    folder.mkdir()
    clear_history_cache()
    report = study_extra_datasets(tmp_path, force=True)
    assert report.found is True
    assert report.files == []
    assert "no ohlcv" in report.note.lower() or "empty" in report.note.lower()
    md = render_history(report)
    assert "Extra datasets" in md


def test_missing_folder_is_honest(tmp_path: Path) -> None:
    clear_history_cache()
    report = study_extra_datasets(tmp_path, force=True)
    assert report.found is False
    assert "No `extra datasets/`" in report.note


def test_histdata_and_yahoo_ingest(tmp_path: Path) -> None:
    folder = tmp_path / "extra datasets"
    folder.mkdir()
    histdata = folder / "EURUSD_M1.csv"
    lines = []
    ts = datetime(2024, 1, 2, 7, 0, tzinfo=timezone.utc)
    price = 1.10200
    for i in range(180):
        minute = ts.hour * 60 + ts.minute + i
        day = ts.strftime("%Y%m%d")
        clock = f"{(minute // 60) % 24:02d}{minute % 60:02d}00"
        price -= 0.00003
        o, h, l, c = price, price + 0.00020, price - 0.00020, price - 0.00005
        lines.append(f"{day} {clock};{o:.5f};{h:.5f};{l:.5f};{c:.5f};0")
    histdata.write_text("\n".join(lines) + "\n", encoding="utf-8")

    yahoo = folder / "EURUSD_yahoo.csv"
    _write_eurusd_csv(yahoo, n=120)

    dxy = folder / "DXY.csv"
    dxy.write_text(
        "Date,Open,High,Low,Close\n"
        "2024-01-02,103.10,103.40,102.90,103.20\n"
        "2024-01-03,103.20,104.10,103.00,103.80\n",
        encoding="utf-8",
    )

    clear_history_cache()
    report = study_extra_datasets(tmp_path, force=True)
    kinds = {item.kind for item in report.files}
    assert "eurusd" in kinds
    assert "dxy" in kinds
    assert report.eurusd_bars >= 100
    assert report.sessions
    assert report.dxy_note and "DXY" in report.dxy_note
    md = write_history(report, tmp_path / "HISTORY.md").read_text(encoding="utf-8")
    assert "session memory" in md.lower() or "EUR/USD" in md


def test_forexite_headerless_and_zip(tmp_path: Path) -> None:
    folder = tmp_path / "extra datasets"
    folder.mkdir()
    raw = folder / "eurusd_forexite.txt"
    lines = []
    for i in range(80):
        lines.append(f"20240304,{8:02d}{i % 60:02d}00,1.08500,1.08540,1.08460,1.08490")
    raw.write_text("\n".join(lines) + "\n", encoding="utf-8")
    zipped = folder / "dump.zip"
    with zipfile.ZipFile(zipped, "w") as archive:
        archive.write(raw, arcname="inside.csv")
    raw.unlink()
    clear_history_cache()
    report = study_extra_datasets(tmp_path, force=True)
    assert report.files
    assert report.files[0].kind == "eurusd"
    assert report.files[0].rows >= 50


def test_classify_and_timeframe() -> None:
    idx = pd.date_range("2024-01-01", periods=30, freq="5min", tz="UTC")
    frame = pd.DataFrame(
        {"open": 1.1, "high": 1.11, "low": 1.09, "close": 1.105},
        index=idx,
    )
    assert classify_ohlc(frame) == "eurusd"
    assert infer_timeframe(idx) == "M5"


def test_history_gate_prefers_replayed_side() -> None:
    from src.data.datasets import HistoryReport

    hist = HistoryReport(
        ts=utcnow(),
        found=True,
        replay_trades=80,
        validated_for_live=True,
        preferred_side="SELL",
        preferred_session="london",
        next_focus="History leans SELL in london.",
    )
    blocked = growth_gate(_signal(action="BUY", strength=50), None, history=hist, settings=Settings())
    assert blocked.allowed is False
    allowed = growth_gate(
        _signal(
            action="SELL",
            stop_loss=1.14710,
            take_profit_1=1.14604,
            take_profit_2=1.14540,
            strength=70,
        ),
        None,
        history=hist,
        settings=Settings(),
    )
    assert allowed.allowed is True
    fade = growth_gate(
        _signal(action="BUY", strength=88, stop_loss=1.1450, take_profit_1=1.1480, take_profit_2=1.1490),
        None,
        history=hist,
        settings=Settings(),
    )
    assert fade.allowed is True
    assert fade.action == "fade"


def test_history_skips_losing_named_setup() -> None:
    from src.data.datasets import HistoryReport

    hist = HistoryReport(
        ts=utcnow(),
        found=True,
        replay_trades=10,
        validated_for_live=True,
        setups=[
            {
                "signal_type": "band_rsi",
                "side": "BUY",
                "session": "london",
                "samples": 40,
                "wins": 10,
                "losses": 30,
                "expectancy_pips": -1.2,
            }
        ],
    )
    blocked = growth_gate(
        _signal(action="BUY", strength=50, signal_type="band_rsi"),
        None,
        history=hist,
        settings=Settings(),
    )
    assert blocked.allowed is False
    assert "band_rsi" in blocked.reason
    strong = growth_gate(
        _signal(action="BUY", strength=88, signal_type="band_rsi", stop_loss=1.1450, take_profit_1=1.1480, take_profit_2=1.1490),
        None,
        history=hist,
        settings=Settings(),
    )
    assert strong.allowed is True


def test_cache_folder_is_ignored(tmp_path: Path) -> None:
    folder = tmp_path / "extra datasets"
    cache = folder / "cache"
    cache.mkdir(parents=True)
    _write_eurusd_csv(cache / "EURUSD_M5_forexsb.csv", n=80)
    (folder / "README.md").write_text("notes", encoding="utf-8")
    clear_history_cache()
    report = study_extra_datasets(tmp_path, force=True)
    assert report.files == []
    assert report.found is True


def test_desktop_extra_datasets_are_discovered(tmp_path: Path, monkeypatch) -> None:
    desk = tmp_path / "Desktop"
    extra = desk / "extra datasets"
    nested = desk / "forex" / "extra datasets"
    extra.mkdir(parents=True)
    nested.mkdir(parents=True)
    _write_eurusd_csv(extra / "desktop_eurusd.csv", n=90)
    _write_eurusd_csv(nested / "forex_folder_eurusd.csv", n=90)
    monkeypatch.setattr("src.data.datasets.home_desktop_dirs", lambda: [desk])
    found = desktop_dataset_dirs()
    assert extra in found
    assert nested in found
    dirs = dataset_dirs(tmp_path / "empty-project", include_desktop=True)
    assert extra in dirs
    assert nested in dirs


def test_study_reads_desktop_dump(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "proj"
    (project / "extra datasets").mkdir(parents=True)
    desk = tmp_path / "Desktop"
    extra = desk / "extra datasets"
    extra.mkdir(parents=True)
    _write_eurusd_csv(extra / "desktop_eurusd.csv", n=120)
    monkeypatch.setattr("src.data.datasets.home_desktop_dirs", lambda: [desk])
    monkeypatch.setattr("src.data.datasets.ROOT", project)
    clear_history_cache()
    report = study_extra_datasets(force=True)
    names = {item.path for item in report.files}
    assert "desktop_eurusd.csv" in names
    assert report.eurusd_bars >= 100


def test_persist_history_book_tags_source(tmp_path: Path, monkeypatch) -> None:
    from sqlalchemy import select

    from src.config import reload_settings
    from src.data.storage import SignalRow, init_db, reset_engine, session_scope

    db = tmp_path / "persist.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    reset_engine()
    reload_settings()
    init_db()
    live_looking = _signal(source="live", action="SELL")
    persist_history_book(None, None, None, [], [live_looking])
    with session_scope() as session:
        rows = list(session.scalars(select(SignalRow)))
        assert len(rows) == 1
        assert rows[0].source == "history"
        assert rows[0].skip_reason == "historical_replay"
        assert rows[0].skipped is True
    reset_engine()
