"""Load optional historical files from ``extra datasets/`` and study them.

The operator can drop EUR/USD OHLCV (and DXY / yields / VIX) as CSV, TSV,
JSON, or Parquet. On startup and whenever the files change the desk scores
session drift and replays the same EMA/RSI setup it trades live, then writes
``desk/HISTORY.md`` so the playbook can hunt with that memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from src.analysis.indicators import compute_indicators
from src.utils import utcnow

ROOT = Path(__file__).resolve().parents[2]
DIR_NAMES = (
    "extra datasets",
    "extra_datasets",
    "Extra Datasets",
    "extra-datasets",
    "ExtraDatasets",
)
DESKTOP_PROJECT_DIRS = (
    "forex",
    "Forex",
    "fx-pulse",
    "Forex Sentinel",
    "forex-sentinel",
    "fx pulse",
)
OHLC_ALIASES = {
    "open": {"open", "o", "bidopen", "price_open", "bo"},
    "high": {"high", "h", "bidhigh", "price_high", "bh"},
    "low": {"low", "l", "bidlow", "price_low", "bl"},
    "close": {"close", "c", "bidclose", "price_close", "adj_close", "adjclose", "bc", "last"},
    "volume": {"volume", "vol", "tickqty", "tick_volume", "v"},
}
TIME_ALIASES = {
    "time",
    "date",
    "datetime",
    "timestamp",
    "gmt_time",
    "local_time",
    "localtime",
    "gmttime",
    "dtyyyymmdd",
    "dt",
}
# Cap the EMA/RSI walk so Supertrend/WMA cannot hold the GIL for minutes.
MAX_ROWS = 12_000
REPLAY_CAP = 8_000


@dataclass(slots=True)
class DatasetFile:
    path: str
    kind: str
    rows: int
    note: str = ""
    start: str | None = None
    end: str | None = None
    timeframe: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "rows": self.rows,
            "note": self.note,
            "start": self.start,
            "end": self.end,
            "timeframe": self.timeframe,
        }


@dataclass(slots=True)
class SessionStat:
    name: str
    samples: int
    mean_range_pips: float
    mean_return_pips: float
    up_share: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "samples": self.samples,
            "mean_range_pips": round(self.mean_range_pips, 2),
            "mean_return_pips": round(self.mean_return_pips, 2),
            "up_share": round(self.up_share, 3),
        }


@dataclass(slots=True)
class ReplayBucket:
    key: str
    trades: int
    wins: int
    losses: int
    expectancy_pips: float
    win_rate: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "expectancy_pips": round(self.expectancy_pips, 2),
            "win_rate": round(self.win_rate, 3),
        }


@dataclass(slots=True)
class HistoryReport:
    ts: datetime
    found: bool
    directories: list[str] = field(default_factory=list)
    files: list[DatasetFile] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    sessions: list[SessionStat] = field(default_factory=list)
    replay: list[ReplayBucket] = field(default_factory=list)
    replay_trades: int = 0
    preferred_side: str | None = None
    preferred_session: str | None = None
    eurusd_bars: int = 0
    eurusd_span: str | None = None
    dxy_note: str | None = None
    rules: list[str] = field(default_factory=list)
    next_focus: str = ""
    note: str = ""
    setups: list[dict[str, Any]] = field(default_factory=list)
    preferred_signal_type: str | None = None
    validated_for_live: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "found": self.found,
            "validated_for_live": self.validated_for_live,
            "directories": list(self.directories),
            "files": [f.as_dict() for f in self.files],
            "skipped": list(self.skipped),
            "sessions": [s.as_dict() for s in self.sessions],
            "replay": [r.as_dict() for r in self.replay],
            "replay_trades": self.replay_trades,
            "preferred_side": self.preferred_side,
            "preferred_session": self.preferred_session,
            "eurusd_bars": self.eurusd_bars,
            "eurusd_span": self.eurusd_span,
            "dxy_note": self.dxy_note,
            "rules": list(self.rules),
            "next_focus": self.next_focus,
            "note": self.note,
            "setups": list(self.setups),
            "preferred_signal_type": self.preferred_signal_type,
        }


_CACHE: HistoryReport | None = None
_CACHE_KEY: tuple | None = None


def home_desktop_dirs() -> list[Path]:
    """Local Desktop folders. Empty in this cloud workspace; present on the operator's machine."""
    home = Path.home()
    candidates: list[Path] = []
    xdg = home / ".config" / "user-dirs.dirs"
    if xdg.is_file():
        try:
            for line in xdg.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("XDG_DESKTOP_DIR="):
                    raw = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(home))
                    candidates.append(Path(raw).expanduser())
        except OSError:
            pass
    candidates.extend(
        [
            home / "Desktop",
            home / "desktop",
            home / "OneDrive" / "Desktop",
            home / "OneDrive" / "desktop",
        ]
    )
    found: list[Path] = []
    for path in candidates:
        try:
            if path.is_dir() and path not in found:
                found.append(path)
        except OSError:
            continue
    return found


def desktop_dataset_dirs() -> list[Path]:
    """Find `extra datasets` sitting on the Desktop, including Desktop/forex/extra datasets."""
    found: list[Path] = []

    def _take(path: Path) -> None:
        try:
            if path.is_dir() and path not in found:
                found.append(path)
        except OSError:
            return

    for desktop in home_desktop_dirs():
        for name in DIR_NAMES:
            _take(desktop / name)
        try:
            for path in desktop.iterdir():
                if path.is_dir() and "dataset" in path.name.lower():
                    _take(path)
        except OSError:
            pass
        for project in DESKTOP_PROJECT_DIRS:
            base = desktop / project
            if not base.is_dir():
                continue
            for name in DIR_NAMES:
                _take(base / name)
            try:
                for path in base.iterdir():
                    if path.is_dir() and "dataset" in path.name.lower():
                        _take(path)
            except OSError:
                pass
    return found


def configured_dataset_dir() -> Path | None:
    try:
        from src.config import get_settings

        raw = (get_settings().extra_datasets_dir or "").strip()
    except Exception:
        return None
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    try:
        path = path.resolve()
        return path if path.is_dir() else None
    except OSError:
        return None


def dataset_dirs(root: Path | None = None, *, include_desktop: bool | None = None) -> list[Path]:
    base = Path(root) if root is not None else ROOT
    found: list[Path] = []
    if include_desktop is None:
        include_desktop = root is None

    def _take(path: Path) -> None:
        try:
            if path.is_dir() and path not in found:
                found.append(path)
        except OSError:
            return

    for name in DIR_NAMES:
        _take(base / name)
    try:
        for path in base.iterdir():
            if path.is_dir() and "dataset" in path.name.lower():
                _take(path)
    except FileNotFoundError:
        pass
    configured = configured_dataset_dir() if root is None else None
    if configured is not None:
        _take(configured)
    if include_desktop:
        for path in desktop_dataset_dirs():
            _take(path)
    return found


TABLE_SUFFIXES = {".csv", ".tsv", ".txt", ".json", ".jsonl", ".parquet", ".dat", ".zip"}


def discover_files(root: Path | None = None) -> list[Path]:
    files: list[Path] = []
    for folder in dataset_dirs(root):
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.name.lower().startswith("readme"):
                continue
            if "cache" in {part.lower() for part in path.parts}:
                continue
            if path.suffix.lower() in TABLE_SUFFIXES:
                files.append(path)
    return files


def _norm_col(name: Any) -> str:
    text = str("" if name is None else name).strip().lower()
    for ch in ("<", ">", " ", "-", "/", "."):
        text = text.replace(ch, "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _parse_delimited(raw: str, *, path_hint: str = "") -> pd.DataFrame | None:
    sample = raw[:4000]
    sep = ";" if sample.count(";") > sample.count(",") else ("\t" if sample.count("\t") > sample.count(",") else ",")
    header: int | None = 0
    first = sample.splitlines()[0] if sample.splitlines() else ""
    if first and not any(token in first.lower() for token in ("open", "close", "date", "time", "ticker")):
        token = first.split(";")[0].split(",")[0].strip().replace('"', "")
        if token[:8].isdigit():
            header = None
    from io import StringIO

    frame = pd.read_csv(StringIO(raw), sep=sep, header=header)
    if frame.shape[1] == 1 and sep != ";":
        frame = pd.read_csv(StringIO(raw), sep=";", header=header)
    if path_hint:
        logger.debug("Parsed extra dataset {} ({} cols)", path_hint, frame.shape[1])
    return frame


def _read_table(path: Path) -> pd.DataFrame | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".zip":
            import zipfile

            with zipfile.ZipFile(path) as archive:
                members = [
                    info
                    for info in archive.infolist()
                    if not info.is_dir()
                    and not Path(info.filename).name.startswith(".")
                    and Path(info.filename).suffix.lower() in {".csv", ".tsv", ".txt", ".dat", ""}
                ]
                if not members:
                    return None
                members.sort(key=lambda info: info.file_size, reverse=True)
                raw = archive.read(members[0]).decode("utf-8", errors="ignore")
                return _parse_delimited(raw, path_hint=f"{path.name}:{members[0].filename}")
        if suffix == ".parquet":
            return pd.read_parquet(path)
        if suffix in {".json", ".jsonl"}:
            try:
                return pd.read_json(path, lines=suffix == ".jsonl")
            except ValueError:
                raw = pd.read_json(path)
                if isinstance(raw, pd.Series):
                    return raw.to_frame()
                return raw
        text = path.read_text(encoding="utf-8", errors="ignore")
        return _parse_delimited(text, path_hint=path.name)
    except Exception as exc:
        logger.warning("Could not read extra dataset {}: {}", path, exc)
        return None


def _is_positional(cols: list[str]) -> bool:
    if len(cols) < 5:
        return False
    if cols == [str(i) for i in range(len(cols))]:
        return True
    return all(str(c).isdigit() for c in cols)


def _parse_datetime(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, utc=True, errors="coerce")
    if parsed.notna().mean() >= 0.5:
        return parsed
    text = series.astype(str).str.replace(r"[^0-9]", "", regex=True)
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
        retry = pd.to_datetime(text, format=fmt, utc=True, errors="coerce")
        if retry.notna().mean() >= 0.5:
            return retry
    return parsed


def _map_ohlc(frame: pd.DataFrame) -> pd.DataFrame | None:
    work = frame.copy()
    work.columns = [_norm_col(c) for c in work.columns]
    cols = list(work.columns)
    if _is_positional(cols):
        first = str(work.iloc[0, 0]) if len(work) else ""
        second = str(work.iloc[0, 1]) if work.shape[1] > 1 and len(work) else ""
        first_digits = "".join(ch for ch in first if ch.isdigit())
        second_digits = "".join(ch for ch in second if ch.isdigit())
        date_only = len(first_digits) in {8, 6}
        time_like = 1 <= len(second_digits) <= 6
        if date_only and time_like and work.shape[1] >= 6:
            names = ["dtyyyymmdd", "time", "open", "high", "low", "close"]
            extra = ["volume"] if work.shape[1] > 6 else []
            work.columns = names + extra + [f"col{i}" for i in range(6 + len(extra), work.shape[1])]
        else:
            names = ["datetime", "open", "high", "low", "close"]
            extra = ["volume"] if work.shape[1] > 5 else []
            work.columns = names + extra + [f"col{i}" for i in range(5 + len(extra), work.shape[1])]
    rename: dict[str, str] = {}
    for dest, aliases in OHLC_ALIASES.items():
        for col in work.columns:
            if col in aliases or col.endswith("_" + dest):
                rename[col] = dest
                break
    work = work.rename(columns=rename)
    if "dtyyyymmdd" in work.columns:
        date_part = work["dtyyyymmdd"].astype(str).str.replace(r"[^0-9]", "", regex=True).str[:8]
        if "time" in work.columns:
            clock = (
                work["time"]
                .astype(str)
                .str.replace(r"[^0-9]", "", regex=True)
                .str.zfill(6)
                .str[:6]
            )
            stamp = date_part + clock
        else:
            stamp = date_part + "000000"
        work["datetime"] = pd.to_datetime(stamp, format="%Y%m%d%H%M%S", utc=True, errors="coerce")
    time_col = next((c for c in work.columns if c in TIME_ALIASES or "time" in c or "date" in c), None)
    if "datetime" not in work.columns and time_col:
        work["datetime"] = _parse_datetime(work[time_col])
    elif "datetime" in work.columns and not pd.api.types.is_datetime64_any_dtype(work["datetime"]):
        work["datetime"] = _parse_datetime(work["datetime"])
    if "datetime" not in work.columns:
        return None
    needed = {"open", "high", "low", "close"}
    if not needed.issubset(work.columns):
        return None
    for col in ("open", "high", "low", "close"):
        work[col] = pd.to_numeric(work[col], errors="coerce")
    if "volume" in work.columns:
        work["volume"] = pd.to_numeric(work["volume"], errors="coerce")
    cols = ["datetime", "open", "high", "low", "close"]
    if "volume" in work.columns:
        cols.append("volume")
    out = work[cols].dropna(subset=["datetime", "open", "high", "low", "close"])
    out = out.sort_values("datetime").drop_duplicates("datetime")
    if out.empty:
        return None
    return out.set_index("datetime")


def _pips_from_price(delta: Any) -> Any:
    return delta * 10000.0


def infer_timeframe(index: pd.DatetimeIndex) -> str:
    if len(index) < 3:
        return "D1"
    values = pd.Series(index).diff().dt.total_seconds().dropna()
    if values.empty:
        return "D1"
    deltas = float(values.median())
    if deltas <= 90:
        return "M1"
    if deltas <= 400:
        return "M5"
    if deltas <= 1200:
        return "M15"
    if deltas <= 2400:
        return "M30"
    if deltas <= 5000:
        return "H1"
    if deltas <= 20000:
        return "H4"
    return "D1"


def classify_ohlc(frame: pd.DataFrame) -> str:
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if close.empty:
        return "unknown"
    median = float(close.median())
    if 0.8 <= median <= 1.7:
        return "eurusd"
    if 80 <= median <= 130:
        return "dxy"
    if 1.5 <= median <= 8 and float(close.std()) < 2:
        return "us10y"
    if 8 <= median <= 90:
        return "vix"
    if 1000 <= median <= 10000:
        return "gold"
    return "fx_other"


def session_name(ts: datetime) -> str:
    hour = int(ts.hour)
    if 0 <= hour < 7:
        return "tokyo"
    if 7 <= hour < 12:
        return "london"
    if 12 <= hour < 16:
        return "overlap"
    if 16 <= hour < 22:
        return "new_york"
    return "off"


def _session_stats(ohlc: pd.DataFrame) -> list[SessionStat]:
    work = ohlc.copy()
    work["session"] = [session_name(idx.to_pydatetime()) for idx in work.index]
    work["range_pips"] = _pips_from_price(work["high"] - work["low"])
    work["ret_pips"] = _pips_from_price(work["close"] - work["open"])
    rows: list[SessionStat] = []
    for name, part in work.groupby("session"):
        if name == "off" or part.empty:
            continue
        rows.append(
            SessionStat(
                name=str(name),
                samples=int(len(part)),
                mean_range_pips=float(part["range_pips"].mean()),
                mean_return_pips=float(part["ret_pips"].mean()),
                up_share=float((part["ret_pips"] > 0).mean()),
            )
        )
    rows.sort(key=lambda item: -abs(item.mean_return_pips))
    return rows


def replay_desk_rules(ohlc: pd.DataFrame, timeframe: str) -> list[ReplayBucket]:
    """Legacy EMA/RSI illustration: sampled closes, no costs; not a live-strategy backtest."""
    frame = ohlc.copy()
    if timeframe == "M1" and len(frame) > 8000:
        how = {"open": "first", "high": "max", "low": "min", "close": "last"}
        if "volume" in frame.columns:
            how["volume"] = "sum"
        frame = frame.resample("5min").agg(how).dropna()
    if len(frame) > MAX_ROWS:
        frame = frame.iloc[-MAX_ROWS:]
    scored = compute_indicators(frame, heavy=False)
    ready = scored.dropna(subset=["ema_fast", "ema_slow", "rsi", "atr"])
    if len(ready) < 80:
        return []
    if len(ready) > REPLAY_CAP:
        step = max(1, len(ready) // REPLAY_CAP)
        ready = ready.iloc[::step]
    results: dict[str, list[float]] = {}
    open_trade: dict[str, Any] | None = None
    for ts, row in ready.iterrows():
        price = float(row["close"])
        atr = float(row["atr"])
        if atr <= 0:
            continue
        when = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        session = session_name(when)
        if open_trade is not None:
            side = open_trade["side"]
            hit = None
            if side == "SELL":
                if price >= open_trade["sl"]:
                    hit = -open_trade["risk"]
                elif price <= open_trade["tp"]:
                    hit = open_trade["reward"]
            else:
                if price <= open_trade["sl"]:
                    hit = -open_trade["risk"]
                elif price >= open_trade["tp"]:
                    hit = open_trade["reward"]
            if hit is not None:
                key = f"{open_trade['side']}|{open_trade['session']}"
                results.setdefault(key, []).append(float(_pips_from_price(hit)))
                open_trade = None
            continue
        ema_fast = float(row["ema_fast"])
        ema_slow = float(row["ema_slow"])
        rsi = float(row["rsi"])
        side = None
        if ema_fast < ema_slow and rsi >= 62:
            side = "SELL"
        elif ema_fast > ema_slow and rsi <= 38:
            side = "BUY"
        if side is None:
            continue
        risk = atr * 1.0
        reward = atr * 1.2
        if side == "SELL":
            open_trade = {
                "side": side,
                "sl": price + risk,
                "tp": price - reward,
                "risk": risk,
                "reward": reward,
                "session": session,
            }
        else:
            open_trade = {
                "side": side,
                "sl": price - risk,
                "tp": price + reward,
                "risk": risk,
                "reward": reward,
                "session": session,
            }
    buckets: list[ReplayBucket] = []
    for key, pips in results.items():
        wins = [item for item in pips if item > 0]
        losses = [item for item in pips if item <= 0]
        buckets.append(
            ReplayBucket(
                key=key,
                trades=len(pips),
                wins=len(wins),
                losses=len(losses),
                expectancy_pips=float(np.mean(pips)) if pips else 0.0,
                win_rate=(len(wins) / len(pips)) if pips else 0.0,
            )
        )
    buckets.sort(key=lambda item: -item.expectancy_pips)
    return buckets


def replay_live_setups(
    m5: pd.DataFrame | None,
    h1: pd.DataFrame | None,
    d1: pd.DataFrame | None,
    settings: Any | None = None,
    *,
    step: int = 1,
    lookback: int = 8_000,
    max_trades: int = 500,
) -> tuple[list[dict[str, Any]], list[Any]]:
    """Exploratory live-signal replay with completed bars and explicit execution costs."""
    from src.analysis.replay import replay
    from src.config import get_settings
    return replay(m5, h1, d1, settings or get_settings(), step=step, lookback=lookback, max_trades=max_trades)


def score_setups(closed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in closed:
        key = (str(row.get("signal_type") or "mixed"), str(row.get("side") or ""), str(row.get("session") or "unknown"))
        buckets.setdefault(key, []).append(row)
    out: list[dict[str, Any]] = []
    for (stype, side, session), rows in buckets.items():
        pips = [float(r["pips"]) for r in rows]
        wins = [p for p in pips if p > 0]
        losses = [p for p in pips if p <= 0]
        out.append(
            {
                "symbol": "EUR/USD",
                "signal_type": stype,
                "side": side,
                "session": session,
                "samples": len(pips),
                "wins": len(wins),
                "losses": len(losses),
                "expectancy_pips": float(np.mean(pips)) if pips else 0.0,
                "win_rate": (len(wins) / len(pips)) if pips else 0.0,
                "avg_strength": float(np.mean([float(r.get("strength") or 0) for r in rows])) if rows else 0.0,
            }
        )
    out.sort(key=lambda item: (-item["expectancy_pips"], -item["samples"]))
    return out


def persist_history_book(
    m5: pd.DataFrame | None,
    h1: pd.DataFrame | None,
    d1: pd.DataFrame | None,
    setups: list[dict[str, Any]],
    signals: list[Any],
) -> None:
    """Write historical bars, indicators, named setups, and sample signals to SQLite."""
    from src.data.storage import (
        insert_signal,
        replace_setup_memory,
        session_scope,
        upsert_bars_fast,
        upsert_indicators,
    )
    from sqlalchemy import text as sql_text

    def _bar_rows(frame: pd.DataFrame | None, timeframe: str, tail: int) -> list[dict[str, Any]]:
        if frame is None or frame.empty:
            return []
        rows = []
        for ts, row in frame.tail(tail).iterrows():
            ts_val = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            if isinstance(ts_val, datetime) and ts_val.tzinfo is None:
                ts_val = ts_val.replace(tzinfo=timezone.utc)
            rows.append(
                {
                    "symbol": "EUR/USD",
                    "timeframe": timeframe,
                    "ts": ts_val,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]) if "volume" in row and row["volume"] == row["volume"] else 0.0,
                    "source": "forexsb",
                    "complete": True,
                }
            )
        return rows

    def _num(row: pd.Series, key: str) -> float | None:
        if key not in row.index:
            return None
        try:
            value = float(row[key])
        except (TypeError, ValueError):
            return None
        if value != value:
            return None
        return value

    def _indicator_rows(frame: pd.DataFrame | None, timeframe: str, tail: int) -> list[dict[str, Any]]:
        if frame is None or frame.empty:
            return []
        scored = compute_indicators(frame.tail(max(tail + 80, 200)))
        ready = scored.dropna(subset=["ema_fast", "ema_slow", "rsi", "atr"])
        rows = []
        for ts, row in ready.tail(tail).iterrows():
            ts_val = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            if isinstance(ts_val, datetime) and ts_val.tzinfo is None:
                ts_val = ts_val.replace(tzinfo=timezone.utc)
            extra = {
                "bb_pct": _num(row, "bb_pct"),
                "macd_signal": _num(row, "macd_signal"),
            }
            trend = _num(row, "trend")
            rows.append(
                {
                    "symbol": "EUR/USD",
                    "timeframe": timeframe,
                    "ts": ts_val,
                    "ema_fast": float(row["ema_fast"]),
                    "ema_slow": float(row["ema_slow"]),
                    "rsi": float(row["rsi"]),
                    "atr": float(row["atr"]),
                    "bb_upper": float(row["bb_upper"]),
                    "bb_mid": float(row["bb_mid"]),
                    "bb_lower": float(row["bb_lower"]),
                    "macd": _num(row, "macd"),
                    "macd_signal": extra["macd_signal"],
                    "macd_hist": _num(row, "macd_hist"),
                    "stoch_k": _num(row, "stoch_k"),
                    "stoch_d": _num(row, "stoch_d"),
                    "adx": _num(row, "adx"),
                    "plus_di": _num(row, "plus_di"),
                    "minus_di": _num(row, "minus_di"),
                    "cci": _num(row, "cci"),
                    "trend": int(trend) if trend is not None else None,
                    "extra": extra,
                }
            )
        return rows

    with session_scope() as session:
        for batch in (
            _bar_rows(m5, "M5", 4_000),
            _bar_rows(h1, "H1", 2_000),
            _bar_rows(d1, "D1", 800),
        ):
            if batch:
                try:
                    upsert_bars_fast(session, batch)
                except Exception:
                    from src.data.storage import upsert_bars

                    upsert_bars(session, batch)
        for batch in (
            _indicator_rows(m5, "M5", 1_200),
            _indicator_rows(h1, "H1", 800),
            _indicator_rows(d1, "D1", 400),
        ):
            if batch:
                upsert_indicators(session, batch)
        memory_rows = []
        now = utcnow()
        for item in setups:
            memory_rows.append(
                {
                    "symbol": "EUR/USD",
                    "signal_type": item["signal_type"],
                    "side": item["side"],
                    "session": item["session"],
                    "samples": int(item["samples"]),
                    "wins": int(item["wins"]),
                    "losses": int(item["losses"]),
                    "expectancy_pips": float(item["expectancy_pips"]),
                    "win_rate": float(item["win_rate"]),
                    "avg_strength": float(item["avg_strength"]),
                    "last_studied": now,
                }
            )
        replace_setup_memory(session, memory_rows, symbol="EUR/USD")
        session.execute(
            sql_text(
                "DELETE FROM signals WHERE source = 'history' "
                "OR skip_reason = 'historical_replay'"
            )
        )
        for sig in signals[-250:]:
            row = sig.to_row(skipped=True, skip_reason="historical_replay")
            row["source"] = "history"
            insert_signal(session, row)
    logger.info(
        "Persisted ForexSB history: {} setups, {} sample signals",
        len(setups),
        min(250, len(signals)),
    )


def _dxy_note(dxy: pd.DataFrame, eurusd: pd.DataFrame | None) -> str:
    last = float(dxy["close"].iloc[-1])
    first = float(dxy["close"].iloc[max(0, len(dxy) - 20)])
    change = ((last - first) / first) * 100 if first else 0.0
    note = f"DXY last {last:.2f} ({change:+.2f}% over the file's recent window)."
    if eurusd is None or eurusd.empty:
        return note + " Rising DXY usually weighs on EUR/USD."
    joined = (
        dxy["close"]
        .resample("1D")
        .last()
        .to_frame("dxy")
        .join(eurusd["close"].resample("1D").last().to_frame("eur"), how="inner")
        .dropna()
    )
    if len(joined) >= 20:
        corr = float(joined["dxy"].pct_change().corr(joined["eur"].pct_change()))
        note += f" Daily correlation with EUR/USD {corr:+.2f}."
    return note


def render_history(report: HistoryReport) -> str:
    lines = [
        "# Extra datasets — historical study",
        "",
        f"_Last studied: {report.ts.strftime('%Y-%m-%d %H:%M UTC')}. Rewritten when files in `extra datasets/` change._",
        "",
        report.note or report.next_focus or "No extra datasets loaded.",
        "",
    ]
    if report.directories:
        lines += ["## Folders", ""]
        lines.extend(f"- `{item}`" for item in report.directories)
        lines.append("")
    if report.files:
        lines += ["## Files", ""]
        for item in report.files:
            span = f" · {item.start} → {item.end}" if item.start and item.end else ""
            tf = f" · {item.timeframe}" if item.timeframe else ""
            lines.append(f"- `{item.path}` · {item.kind} · {item.rows} rows{tf}{span} {item.note}".rstrip())
        lines.append("")
    if report.sessions:
        lines += ["## EUR/USD session memory", ""]
        for sess in report.sessions:
            lines.append(
                f"- **{sess.name}**: {sess.samples} bars, mean range {sess.mean_range_pips:.1f} pips, "
                f"mean drift {sess.mean_return_pips:+.2f} pips, up-share {sess.up_share:.0%}."
            )
        lines.append("")
    if report.replay:
        lines += ["## Replay of the live EMA/RSI idea", ""]
        for bucket in report.replay[:12]:
            lines.append(
                f"- `{bucket.key}` · {bucket.wins}W/{bucket.losses}L · "
                f"E {bucket.expectancy_pips:+.1f} pips · win {bucket.win_rate:.0%}"
            )
        lines.append("")
    if report.dxy_note:
        lines += ["## Macro files", "", f"- {report.dxy_note}", ""]
    if report.setups:
        lines += ["## Signal types that paid in this history", ""]
        for item in report.setups[:12]:
            lines.append(
                f"- `{item.get('signal_type')}` {item.get('side')} in {item.get('session')} · "
                f"{item.get('wins')}W/{item.get('losses')}L · E {item.get('expectancy_pips'):+.1f} pips · "
                f"win {item.get('win_rate'):.0%}"
            )
        lines.append("")
    if report.rules:
        lines += ["## Rules taken from this history", ""]
        lines.extend(f"- {item}" for item in report.rules)
        lines.append("")
    if report.skipped:
        lines += ["## Skipped", ""]
        lines.extend(f"- {item}" for item in report.skipped[:20])
        lines.append("")
    return "\n".join(lines) + "\n"


def write_history(report: HistoryReport, path: Path | None = None) -> Path:
    from src.analysis.playbook import HISTORY_PATH, ensure_desk_dir

    ensure_desk_dir()
    target = path or HISTORY_PATH
    target.write_text(render_history(report), encoding="utf-8")
    return target


def study_extra_datasets(root: Path | None = None, *, force: bool = False, persist: bool = False) -> HistoryReport:
    """Parse extra datasets and cache until the files change."""
    global _CACHE, _CACHE_KEY
    files = discover_files(root)
    base = Path(root) if root is not None else ROOT
    key = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in files)
    dirs: list[str] = []
    for folder in dataset_dirs(root):
        try:
            dirs.append(str(folder.relative_to(base)))
        except ValueError:
            dirs.append(str(folder))
    if not force and _CACHE is not None and key == _CACHE_KEY:
        return _CACHE
    ts = utcnow()
    if not files:
        report = HistoryReport(
            ts=ts,
            found=bool(dirs),
            directories=dirs,
            note=(
                "Found extra datasets folder(s), but they have no OHLCV files yet. "
                "This cloud desk cannot see your local Desktop — copy the files into "
                "this project's `extra datasets/` folder, or run the bot on your machine "
                "so it can read Desktop/extra datasets."
                if dirs
                else "No `extra datasets/` folder in this workspace yet. Drop EUR/USD CSV/JSON/Parquet there, or keep them on your Desktop as `extra datasets` when you run the bot locally."
            ),
            next_focus="Waiting on historical files in extra datasets/ (or Desktop/extra datasets when running locally).",
        )
        _CACHE, _CACHE_KEY = report, key
        return report

    loaded: list[DatasetFile] = []
    skipped: list[str] = []
    eurusd_by_tf: dict[str, list[pd.DataFrame]] = {}
    dxy_frame: pd.DataFrame | None = None
    for path in files:
        raw = _read_table(path)
        if raw is None or raw.empty:
            skipped.append(f"{path.name}: unreadable")
            continue
        from src.data.dukascopy import audit_frame, is_second_export

        if is_second_export(path):
            try:
                audit = audit_frame(raw, path_hint=path.name)
            except ValueError as exc:
                skipped.append(f"{path.name}: invalid second export: {exc}")
                continue
            quality = audit["quality"]
            loaded.append(DatasetFile(
                path=path.name, kind="eurusd", rows=audit["rows"],
                start=audit["start_utc"], end=audit["end_utc"], timeframe="S1",
                note=(f"{audit['price_basis']}-only research; "
                      f"{quality['coverage_fraction']:.1%} observed-second coverage; "
                      f"{quality['absent_seconds']} absent seconds. "
                      "Excluded from midpoint replay; run python -m src.data.dukascopy for audit."),
            ))
            continue
        ohlc = _map_ohlc(raw)
        if ohlc is None:
            skipped.append(f"{path.name}: no OHLC columns I could map")
            continue
        kind = classify_ohlc(ohlc)
        tf = infer_timeframe(ohlc.index)
        loaded.append(
            DatasetFile(
                path=path.name,
                kind=kind,
                rows=int(len(ohlc)),
                start=ohlc.index[0].strftime("%Y-%m-%d"),
                end=ohlc.index[-1].strftime("%Y-%m-%d"),
                timeframe=tf,
            )
        )
        if kind == "eurusd":
            eurusd_by_tf.setdefault(tf, []).append(ohlc)
        elif kind == "dxy":
            dxy_frame = ohlc if dxy_frame is None else pd.concat([dxy_frame, ohlc]).sort_index()
        else:
            loaded[-1].note = f"kept as {kind} context"

    def _join(tf: str) -> pd.DataFrame | None:
        frames = eurusd_by_tf.get(tf) or []
        if not frames:
            return None
        out = pd.concat(frames).sort_index()
        out = out[~out.index.duplicated(keep="last")]
        return None if out.empty else out

    def _first(*frames: pd.DataFrame | None) -> pd.DataFrame | None:
        for frame in frames:
            if frame is not None and not frame.empty:
                return frame
        return None

    m5 = _join("M5")
    if m5 is None:
        m1 = _join("M1")
        if m1 is not None:
            how = {"open": "first", "high": "max", "low": "min", "close": "last"}
            if "volume" in m1:
                how["volume"] = "sum"
            counts = m1["close"].resample("5min").count()
            m5 = m1.resample("5min").agg(how).loc[counts == 5].dropna()
    h1 = _join("H1")
    d1 = _join("D1")
    eurusd = _first(m5, h1, d1, _join("M30"))

    sessions: list[SessionStat] = []
    replay: list[ReplayBucket] = []
    preferred_side = None
    preferred_session = None
    preferred_signal_type = None
    setups: list[dict[str, Any]] = []
    hist_signals: list[Any] = []
    rules: list[str] = []
    focus = "Loaded extra datasets but none looked like EUR/USD OHLCV."
    if any(item.kind == "eurusd" and item.timeframe == "S1" for item in loaded):
        focus = "Recognized EUR/USD second exports for research; single-side observations are excluded from midpoint replay."
    span = None
    bars = 0
    if eurusd is not None and not eurusd.empty:
        bars = int(len(eurusd))
        span = f"{eurusd.index[0].strftime('%Y-%m-%d')} → {eurusd.index[-1].strftime('%Y-%m-%d')}"
        sessions = _session_stats(eurusd)
        replay = replay_desk_rules(eurusd, infer_timeframe(eurusd.index))
        replay_trades = sum(item.trades for item in replay)
        closed, hist_signals = replay_live_setups(m5, h1, d1)
        setups = score_setups(closed)
        if replay:
            side_score = {"BUY": 0.0, "SELL": 0.0}
            side_n = {"BUY": 0, "SELL": 0}
            for bucket in replay:
                side = bucket.key.split("|", 1)[0]
                side_score[side] = side_score.get(side, 0.0) + bucket.expectancy_pips * bucket.trades
                side_n[side] = side_n.get(side, 0) + bucket.trades
            preferred_side = max(("SELL", "BUY"), key=lambda side: (side_score[side] / side_n[side] if side_n[side] else -999, side_n[side]))
            best = replay[0]
            preferred_session = best.key.split("|", 1)[-1]
            rules.append(
                f"History ({span}, {bars} bars): replayed EMA/RSI idea {replay_trades} times. "
                f"Best bucket `{best.key}` at {best.expectancy_pips:+.1f} pips expectancy."
            )
            rules.append(
                f"Legacy illustration leans {preferred_side} in {preferred_session}; "
                "not validated for live entry decisions."
            )
            focus = rules[0]
        elif sessions:
            top = sessions[0]
            preferred_session = top.name
            direction = "SELL" if top.mean_return_pips < 0 else "BUY"
            preferred_side = direction if abs(top.mean_return_pips) >= 0.15 else None
            rules.append(
                f"History ({span}): {top.name} has the strongest drift ({top.mean_return_pips:+.2f} pips/bar). "
                "Descriptive drift only, not a trading recommendation."
            )
            focus = rules[0]
        else:
            focus = f"Loaded {bars} EUR/USD bars ({span}) but not enough structure to replay."
        if setups:
            best = setups[0]
            rules.append(
                f"Exploratory named setup `{best['signal_type']}` {best['side']} in {best['session']}: "
                f"{best['expectancy_pips']:+.1f} pips over {best['samples']} historical tickets."
            )
            preferred_signal_type = best["signal_type"]
            if not preferred_side:
                preferred_side = best["side"]
            if not preferred_session:
                preferred_session = best["session"]
        if persist:
            try:
                persist_history_book(m5, h1, d1, setups, hist_signals)
            except Exception:
                logger.exception("Could not persist historical bars/indicators/setups")

    dxy_note = _dxy_note(dxy_frame, eurusd) if dxy_frame is not None else None
    if dxy_note:
        rules.append(dxy_note)

    report = HistoryReport(
        ts=ts,
        found=True,
        directories=dirs,
        files=loaded,
        skipped=skipped,
        sessions=sessions,
        replay=replay,
        replay_trades=sum(item.trades for item in replay),
        preferred_side=preferred_side,
        preferred_session=preferred_session,
        eurusd_bars=bars,
        eurusd_span=span,
        dxy_note=dxy_note,
        rules=rules[:8],
        next_focus=focus,
        note=focus,
        setups=setups[:16],
        preferred_signal_type=preferred_signal_type,
    )
    _CACHE, _CACHE_KEY = report, key
    logger.info(
        "Extra datasets: {} file(s), {} EUR/USD bars, preferred={} session={}",
        len(loaded),
        bars,
        preferred_side,
        preferred_session,
    )
    return report


def clear_history_cache() -> None:
    global _CACHE, _CACHE_KEY
    _CACHE = None
    _CACHE_KEY = None
