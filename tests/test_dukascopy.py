from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.data.dukascopy import audit_csv, audit_frame, main
from src.data.datasets import clear_history_cache, study_extra_datasets, render_history

NAME = "EUR-USD_1Second_BID_2026-09-24.csv"


def sample():
    return pd.DataFrame([
        ["2026-09-24T01:00:00-05:00", 1.1, 1.1002, 1.0999, 1.1001, 100],
        ["2026-09-24T01:00:02-05:00", 1.1001, 1.1005, 1.1, 1.1004, 200],
        ["2026-09-24T01:10:00-05:00", 1.1004, 1.1006, 1.1003, 1.1005, 300],
    ], columns=["America/Chicago", "Open", "High", "Low", "Close", "Volume"])


def test_audit_preserves_quote_basis_gaps_and_empty_bins():
    report = audit_frame(sample(), path_hint=NAME)
    assert report["start_utc"] == "2026-09-24T06:00:00+00:00"
    assert report["price_basis"] == "BID"
    assert report["source_timeframe"] == "S1"
    assert not report["eligible_for_midpoint_replay"]
    assert report["quality"]["absent_seconds"] == 598
    assert report["summary"]["range_pips"] == pytest.approx(7)
    assert report["summary"]["net_pips"] == pytest.approx(5)
    assert [b["observed_seconds"] for b in report["m5"]] == [2, 0, 1]
    assert report["m5"][1]["close"] is None
    assert not report["m5"][0]["full_second_grid"]
    assert report["m5"][-1]["boundary_partial"]
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("case,match", [
    ("duplicate", "Duplicate"), ("unsorted", "Unsorted"),
    ("naive", "UTC offset"), ("timezone", "disagrees"),
    ("geometry", "geometry"), ("infinity", "Nonfinite"),
    ("negative_volume", "nonnegative"), ("subsecond", "subsecond"),
])
def test_bad_inputs_are_not_silently_repaired(case, match):
    frame = sample()
    if case == "duplicate":
        frame.iloc[1, 0] = frame.iloc[0, 0]
    elif case == "unsorted":
        frame = frame.iloc[::-1]
    elif case == "naive":
        frame.iloc[0, 0] = "2026-09-24T01:00:00"
    elif case == "timezone":
        frame.iloc[0, 0] = "2026-09-24T01:00:00-06:00"
    elif case == "geometry":
        frame.iloc[0, 2] = 1.0
    elif case == "infinity":
        frame.iloc[0, 2] = float("inf")
    elif case == "negative_volume":
        frame.iloc[0, 5] = -1
    elif case == "subsecond":
        frame.iloc[0, 0] = "2026-09-24T01:00:00.500-05:00"
    with pytest.raises(ValueError, match=match):
        audit_frame(frame, path_hint=NAME)


def test_dst_fallback_distinguishes_repeated_local_hour():
    frame = sample().iloc[:2].copy()
    frame.iloc[0, 0] = "2026-11-01T01:30:00-05:00"
    frame.iloc[1, 0] = "2026-11-01T01:30:00-06:00"
    result = audit_frame(frame, path_hint=NAME)
    assert result["quality"]["expected_seconds_between_endpoints"] == 3601


def test_other_pairs_and_unknown_basis_rejected():
    for name in ("GBP-USD_1Second_BID_sample.csv", "EUR-USD_1Second_MID_sample.csv"):
        with pytest.raises(ValueError, match="Expected an EUR"):
            audit_frame(sample(), path_hint=name)
    assert audit_frame(sample(), path_hint=NAME.replace("BID", "ASK"))["price_basis"] == "ASK"


def test_sha_and_source_unchanged(tmp_path: Path):
    path = tmp_path / NAME
    sample().to_csv(path, index=False)
    before = path.read_bytes()
    report = audit_csv(path)
    assert len(report["source_sha256"]) == 64
    assert path.read_bytes() == before


def test_cli_writes_json_and_refuses_overwrite(tmp_path: Path, monkeypatch):
    path, output = tmp_path / NAME, tmp_path / "audit.json"
    sample().to_csv(path, index=False)
    monkeypatch.setattr("sys.argv", ["audit", str(path), "--output", str(output)])
    main()
    assert json.loads(output.read_text())["rows"] == 3
    before = output.read_bytes()
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert output.read_bytes() == before


def test_history_recognizes_seconds_without_replaying(tmp_path: Path, monkeypatch):
    folder = tmp_path / "extra datasets"
    folder.mkdir()
    sample().to_csv(folder / NAME, index=False)
    monkeypatch.setattr("src.data.datasets.dataset_dirs", lambda root=None: [folder])
    def unexpected_replay(*args, **kwargs):
        pytest.fail("Single-sided second data must not reach midpoint replay")
    monkeypatch.setattr("src.data.datasets.replay_live_setups", unexpected_replay)
    monkeypatch.setattr("src.data.datasets.replay_desk_rules", unexpected_replay)
    clear_history_cache()
    report = study_extra_datasets(tmp_path, force=True)
    assert report.files[0].timeframe == "S1"
    assert report.files[0].rows == 3
    assert report.eurusd_bars == report.replay_trades == 0
    assert not report.validated_for_live
    assert "BID-only research" in render_history(report)
    clear_history_cache()
