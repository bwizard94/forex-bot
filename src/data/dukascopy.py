"""Offline audit of EUR/USD Dukascopy-format one-second BID/ASK CSV exports.

Observed candles are research data, never midpoint replay input. No network,
broker, settings, database, or order clients are used by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

EXPORT_NAME = re.compile(r"^([A-Z]{3})-?([A-Z]{3})_1Second_(BID|ASK)_", re.I)
PRICE_COLUMNS = ["open", "high", "low", "close"]


def is_second_export(path: str | Path) -> bool:
    return bool(EXPORT_NAME.match(Path(path).name))


def audit_frame(raw: pd.DataFrame, *, path_hint: str) -> dict:
    """Validate without sorting, dropping bad rows, or filling absent seconds.

    Scope is the offset-bearing ISO export supplied by the operator. Other
    Dukascopy formats (ticks, GMT date strings, Renko) need separate adapters.
    Coverage describes recorded seconds, not proof of feed availability.
    """
    match = EXPORT_NAME.match(Path(path_hint).name)
    if not match or match.group(1).upper() + match.group(2).upper() != "EURUSD":
        raise ValueError("Expected an EUR-USD_1Second_BID_ or EUR-USD_1Second_ASK_ filename")
    if raw.empty:
        raise ValueError("Export contains no observations")
    names = [str(c).strip().lstrip("\ufeff") for c in raw.columns]
    if len(names) != 6 or [c.lower() for c in names[1:]] != PRICE_COLUMNS + ["volume"]:
        raise ValueError("Expected timezone,Open,High,Low,Close,Volume columns")
    try:
        zone = ZoneInfo(names[0])
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("First column must name an IANA timezone (e.g. America/Chicago or UTC)") from exc
    stamps = raw.iloc[:, 0].astype(str).str.strip()
    if not stamps.str.contains(r"(?:Z|[+-]\d{2}:\d{2})$", regex=True).all():
        raise ValueError("Every timestamp must include its UTC offset; naive times are ambiguous")
    try:
        parsed = [pd.Timestamp(value) for value in stamps]
        if any(t.utcoffset() != t.tz_convert(zone).utcoffset() for t in parsed):
            raise ValueError("Timestamp offset disagrees with header timezone")
        index = pd.DatetimeIndex(pd.to_datetime(stamps, utc=True, errors="raise", format="mixed"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid export timestamps: {exc}") from exc
    if index.has_duplicates:
        raise ValueError("Duplicate timestamps; source must be reconciled before analysis")
    if not index.is_monotonic_increasing:
        raise ValueError("Unsorted timestamps; source must be reconciled before analysis")
    if (index.asi8 % 1_000_000_000 != 0).any():
        raise ValueError("Expected one-second candle timestamps, not subsecond ticks")
    frame = raw.iloc[:, 1:].copy()
    frame.columns = PRICE_COLUMNS + ["volume"]
    frame = frame.apply(pd.to_numeric, errors="raise").astype(float)
    frame.index = index
    if not np.isfinite(frame.to_numpy()).all():
        raise ValueError("Nonfinite or missing price/volume")
    if (frame[PRICE_COLUMNS] <= 0).any().any() or (frame.volume < 0).any():
        raise ValueError("Prices must be positive and volume nonnegative")
    if ((frame.high < frame[["open", "close", "low"]].max(axis=1)) |
            (frame.low > frame[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("Invalid OHLC geometry")

    first, last = index[0], index[-1]
    expected = int((last - first).total_seconds()) + 1
    gaps = index.to_series().diff().dt.total_seconds()
    gap_rows = []
    for end, seconds in gaps[gaps > 1].nlargest(5).items():
        gap_rows.append({"after_utc": (end - pd.Timedelta(seconds=seconds)).isoformat(),
                         "next_utc": end.isoformat(), "elapsed_seconds": int(seconds),
                         "absent_seconds": int(seconds) - 1})

    def bars(rule: str, duration: int) -> list[dict]:
        # Reindex only the aggregated timeline; empty buckets stay explicitly empty.
        agg = frame.resample(rule, origin="epoch", closed="left", label="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"})
        count = frame.close.resample(rule, origin="epoch", closed="left", label="left").count()
        out = []
        for ts, row in agg.iterrows():
            n = int(count.loc[ts])
            out.append({"bar_open_utc": ts.isoformat(), "observed_seconds": n,
                        "interval_seconds": duration, "coverage_fraction": n / duration,
                        "full_second_grid": n == duration,
                        "boundary_partial": ts < first or ts + pd.Timedelta(seconds=duration) > last + pd.Timedelta(seconds=1),
                        **{c: float(row[c]) if n else None for c in PRICE_COLUMNS},
                        "range_pips": round(float(row.high - row.low) * 10000, 3) if n else None,
                        "net_pips": round(float(row.close - row.open) * 10000, 3) if n else None})
        return out

    minute = bars("1min", 60)
    high_at, low_at = frame.high.idxmax(), frame.low.idxmin()
    return {
        "schema": "dukascopy_second_audit_v1", "symbol": "EUR/USD",
        "source_format": "Dukascopy-style export; filename attribution, not authenticated provenance",
        "source_file": Path(path_hint).name, "source_timezone": names[0],
        "price_basis": match.group(3).upper(), "source_timeframe": "S1",
        "timestamp_convention": "bar-open assumed from export format",
        "volume_semantics": "unverified; excluded from price calculations and signal weighting",
        "validated_for_live": False, "eligible_for_midpoint_replay": False,
        "rows": len(frame), "start_utc": first.isoformat(), "end_utc": last.isoformat(),
        "quality": {"expected_seconds_between_endpoints": expected,
                    "absent_seconds": expected - len(frame), "coverage_fraction": len(frame) / expected,
                    "duplicate_timestamps": 0, "invalid_rows": 0,
                    "gap_count": int((gaps > 1).sum()),
                    "max_gap_elapsed_seconds": int(gaps.max()) if len(frame) > 1 else 0,
                    "largest_gaps": gap_rows},
        "summary": {"first_open": float(frame.open.iloc[0]), "last_close": float(frame.close.iloc[-1]),
                    "high": float(frame.high.max()), "high_at_utc": high_at.isoformat(),
                    "low": float(frame.low.min()), "low_at_utc": low_at.isoformat(),
                    "range_pips": round(float(frame.high.max() - frame.low.min()) * 10000, 3),
                    "net_pips": round(float(frame.close.iloc[-1] - frame.open.iloc[0]) * 10000, 3)},
        "hourly": bars("1h", 3600), "m5": bars("5min", 300),
        "largest_m1_ranges": sorted((b for b in minute if b["observed_seconds"]),
                                    key=lambda b: b["range_pips"], reverse=True)[:10],
        "limitations": [
            "Absent seconds are not forward-filled; their cause is unknown.",
            "OHLC does not reveal the order of intrasecond high/low touches.",
            "A single quote side cannot establish historical spread or executable round-trip P/L.",
            "Aggregates describe observed prices, not certified complete market bars.",
            "Export endpoints are not a verified trading-day open/close.",
        ],
    }


def audit_csv(path: Path) -> dict:
    import io

    payload = path.read_bytes()
    report = audit_frame(pd.read_csv(io.BytesIO(payload)), path_hint=path.name)
    report["source_sha256"] = hashlib.sha256(payload).hexdigest()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--output", type=Path, help="New JSON report path; never overwrites a file")
    args = parser.parse_args()
    try:
        report = audit_csv(args.csv)
        result = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(result)
            print(f"Wrote {args.output}; research only, midpoint replay ineligible.")
        else:
            print(result, end="")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Export audit failed: {exc}\n")


if __name__ == "__main__":
    main()
