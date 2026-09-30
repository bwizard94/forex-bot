"""Bounded, read-only indicator diagnostics; never changes trading decisions."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.compare_strategies import complete_m5
from src.analysis.documentation import atomic_write
from src.analysis.indicators import compute_indicators
from src.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "data/research/indicator-audit/latest.json"
PARAMETERS = ("ema_fast", "ema_slow", "rsi_period", "atr_period", "bb_period", "bb_std")
LIMITATIONS = [
    "Sampled M5 indicator audit, not an exhaustive signal/execution audit or profitability test.",
    "Warm-up differences are diagnostics, not proof that a trade decision changed.",
    "Session VWAP can differ when truncated history starts inside a session.",
    "No automatic strategy suspension, promotion, sizing or broker operations.",
]


def code_hashes():
    return {name: hashlib.sha256((ROOT / "src/analysis" / name).read_bytes()).hexdigest()
            for name in ("indicator_audit.py", "indicators.py")}


def audit_frame(frame, *, calculator=compute_indicators, parameters=None):
    frame = frame.tail(600).copy()
    result = {"status": "insufficient_data", "bars": len(frame),
              "lookahead_checks": 0, "lookahead_mismatches": [], "warmup_mismatches": [],
              "untested_columns": [], "validated_for_live": False, "limitations": LIMITATIONS}
    if len(frame) < 600:
        return result
    if (not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None
            or not frame.index.is_unique or not frame.index.is_monotonic_increasing):
        raise ValueError("Audit requires unique increasing timezone-aware timestamps")
    values = frame[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Non-finite input data")
    result.update(input_sha256=hashlib.sha256(frame.to_csv().encode()).hexdigest(),
                  first_bar=frame.index[0].isoformat(), last_bar=frame.index[-1].isoformat(),
                  tolerance={"rtol": 1e-9, "atol": 1e-10})
    kwargs = dict(parameters or {}, heavy=True)
    full = calculator(frame.copy(), **kwargs)
    columns = [c for c in full if c not in frame]
    if not columns or not full.index.equals(frame.index):
        raise ValueError("Indicator calculator returned invalid schema")
    tested = set()

    def compare(expected, actual, timestamp, target, history):
        if set(actual.index) != set(full.columns):
            raise ValueError("Indicator schema changes with available history")
        for column in columns:
            a, b = expected[column], actual[column]
            if pd.isna(a) and pd.isna(b):
                continue
            tested.add(column)
            if (pd.isna(a) or pd.isna(b) or not np.isfinite(float(a))
                    or not np.isfinite(float(b))
                    or not np.isclose(float(a), float(b), rtol=1e-9, atol=1e-10)):
                target.append({"column": column, "at": timestamp.isoformat(),
                               "history_bars": history,
                               "reference": float(a) if pd.notna(a) and np.isfinite(float(a)) else None,
                               "observed": float(b) if pd.notna(b) and np.isfinite(float(b)) else None})

    # Same past, different future: a causal feature cannot change on a past bar.
    for length in (300, 360, 420, 480, 540, 599):
        prefix = frame.iloc[:length]
        sliced = calculator(prefix.copy(), **kwargs)
        if not sliced.index.equals(prefix.index):
            raise ValueError("Indicator calculator changed prefix timestamps")
        compare(full.iloc[length-1], sliced.iloc[-1], prefix.index[-1],
                result["lookahead_mismatches"], length)
        result["lookahead_checks"] += 1
    prefix_tested = set(tested)
    # Same endpoint, different past: exposes recursive initialization sensitivity.
    for length in (150, 300, 450):
        suffix = frame.tail(length)
        sliced = calculator(suffix.copy(), **kwargs)
        if not sliced.index.equals(suffix.index):
            raise ValueError("Indicator calculator changed warm-up timestamps")
        compare(full.iloc[-1], sliced.iloc[-1], frame.index[-1],
                result["warmup_mismatches"], length)
    result["untested_columns"] = sorted(set(columns) - prefix_tested)
    result["tested_columns"] = len(prefix_tested)
    result["lookahead_status"] = ("mismatch" if result["lookahead_mismatches"]
                                  else "inconclusive" if result["untested_columns"] else "no_mismatch_detected")
    result["status"] = ("attention_required" if result["lookahead_mismatches"] or result["warmup_mismatches"]
                        else "inconclusive" if result["untested_columns"] else "no_mismatch_detected")
    return result


def save_report(report, path=REPORT, desk=None):
    now = report["evaluated_at"]
    atomic_write(path, json.dumps(report, indent=2, allow_nan=False) + "\n")
    atomic_write(path.parent / "runs" / (now.replace(":", "").replace("+", "_") + ".json"),
                 json.dumps(report, indent=2, allow_nan=False) + "\n")
    target = desk or ROOT / "desk"
    lines = ["# Indicator integrity audit", "", f"Status: **{report['status']}**",
             f"Evaluated: {now}", "", f"Lookahead: {report.get('lookahead_status', 'not evaluated')}",
             f"Prefix checkpoints: {report.get('lookahead_checks', 0)}",
             f"Warm-up mismatches: {len(report.get('warmup_mismatches', []))}", "",
             "## Interpretation", "", *("- " + item for item in LIMITATIONS), "",
             "Details and versioned evidence: data/research/indicator-audit/.", ""]
    for kind in ("lookahead_mismatches", "warmup_mismatches"):
        names = sorted({row["column"] for row in report.get(kind, [])})
        lines.append(f"- {kind}: " + (", ".join(names) or "none recorded"))
    atomic_write(target / "INDICATOR_AUDIT.md", "\n".join(lines) + "\n")


def run(path=REPORT):
    now = pd.Timestamp.now(tz="UTC")
    settings = get_settings()
    parameters = {name: getattr(settings, name) for name in PARAMETERS}
    try:
        if not settings.database_url.startswith("sqlite:///"):
            raise ValueError("Indicator audit currently requires SQLite")
        database = Path(settings.database_url.removeprefix("sqlite:///")).resolve()
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            frame = pd.read_sql_query(
                "SELECT ts,open,high,low,close,volume FROM bars WHERE symbol='EUR/USD' "
                "AND timeframe='M1' AND source='oanda' ORDER BY ts DESC LIMIT 4500", connection)
        frame.index = pd.to_datetime(frame.pop("ts"), utc=True)
        frame = frame.sort_index()
        if not frame.index.is_unique:
            raise ValueError("Duplicate source bars")
        frame = frame.loc[frame.index + pd.Timedelta(minutes=1) <= now]
        report = audit_frame(complete_m5(frame), parameters=parameters)
    except Exception as exc:
        report = {"status": "failed", "error_type": type(exc).__name__,
                  "validated_for_live": False, "limitations": LIMITATIONS}
    report.update(evaluated_at=now.isoformat(), source_hashes=code_hashes(), parameters=parameters)
    save_report(report, path)
    return report


def read_status(path=REPORT, now=None):
    try:
        report = json.loads(path.read_text())
        checked = datetime.fromisoformat(report["evaluated_at"])
        current = now or datetime.now(timezone.utc)
        if checked.tzinfo is None or (current - checked).total_seconds() > 8 * 3600:
            report["status"] = "stale"
        elif report["status"] == "failed":
            pass
        elif report["source_hashes"] != code_hashes():
            report["status"] = "source_changed"
        elif report["parameters"] != {name: getattr(get_settings(), name) for name in PARAMETERS}:
            report["status"] = "settings_changed"
        report["lookahead_mismatch_count"] = len(report.get("lookahead_mismatches", []))
        report["warmup_mismatch_count"] = len(report.get("warmup_mismatches", []))
        return {key: value for key, value in report.items()
                if key not in {"source_hashes", "parameters", "lookahead_mismatches", "warmup_mismatches"}}
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "not_evaluated", "validated_for_live": False}


if __name__ == "__main__":
    print(json.dumps(run()))
