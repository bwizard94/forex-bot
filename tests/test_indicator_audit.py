import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from src.analysis import indicator_audit as audit


def bars(count=600):
    close = 1.1 + np.sin(np.arange(count) / 17) * .002
    return pd.DataFrame({"open": close, "high": close + .0002,
                         "low": close - .0002, "close": close,
                         "volume": np.arange(count) % 70 + 10},
                        index=pd.date_range("2026-01-01", periods=count, freq="5min", tz="UTC"))


def test_future_leak_is_detected():
    def leaky(frame, **kwargs):
        return frame.assign(future=frame.close.shift(-1), global_mean=frame.close.mean())
    report = audit.audit_frame(bars(), calculator=leaky)
    assert report["lookahead_status"] == "mismatch"
    assert {x["column"] for x in report["lookahead_mismatches"]} == {"future", "global_mean"}
    assert not report["validated_for_live"]


def test_causal_rolling_feature_passes():
    report = audit.audit_frame(bars(), calculator=lambda f, **kw: f.assign(mean=f.close.rolling(20).mean()))
    assert report["status"] == "no_mismatch_detected"
    assert report["lookahead_checks"] == 6
    assert report["tested_columns"] == 1


def test_recursive_feature_has_warmup_sensitivity_without_future_leak():
    report = audit.audit_frame(bars(), calculator=lambda f, **kw: f.assign(mean=f.close.ewm(span=200).mean()))
    assert report["lookahead_status"] == "no_mismatch_detected"
    assert report["warmup_mismatches"]
    assert report["status"] == "attention_required"


def test_insufficient_and_unexercised_features_do_not_pass():
    assert audit.audit_frame(bars(50))["status"] == "insufficient_data"
    report = audit.audit_frame(bars(), calculator=lambda f, **kw: f.assign(unavailable=np.nan))
    assert report["status"] == "inconclusive"
    assert report["untested_columns"] == ["unavailable"]


def test_bad_timestamps_are_rejected():
    frame = bars()
    frame.index = [frame.index[0]] * len(frame)
    with pytest.raises(ValueError):
        audit.audit_frame(frame)


def test_real_indicators_do_not_change_when_future_bars_removed():
    report = audit.audit_frame(bars())
    assert report["lookahead_status"] == "no_mismatch_detected"
    assert report["tested_columns"] > 50


def test_failed_and_stale_reports_never_look_successful(tmp_path):
    path = tmp_path / "latest.json"
    now = datetime.now(timezone.utc)
    audit.save_report({"status": "failed", "evaluated_at": now.isoformat()},
                      path, desk=tmp_path / "desk")
    assert audit.read_status(path, now)["status"] == "failed"
    assert audit.read_status(path, now + timedelta(hours=9))["status"] == "stale"
    assert (tmp_path / "desk/INDICATOR_AUDIT.md").exists()


def test_changed_code_and_settings_invalidate_old_results(tmp_path):
    path = tmp_path / "latest.json"
    now = datetime.now(timezone.utc)
    report = {"status": "no_mismatch_detected", "evaluated_at": now.isoformat(),
              "source_hashes": {}, "parameters": {}}
    path.write_text(json.dumps(report))
    assert audit.read_status(path, now)["status"] == "source_changed"
    report["source_hashes"] = audit.code_hashes()
    path.write_text(json.dumps(report))
    assert audit.read_status(path, now)["status"] == "settings_changed"


def test_audit_worker_failure_does_not_stop_prospective_research(monkeypatch):
    from src.analysis import strategy_lab_job as job
    import subprocess
    calls = []
    def worker(args, **kwargs):
        calls.append((args, kwargs))
        if "src.analysis.indicator_audit" in args:
            raise subprocess.TimeoutExpired(args, 90)
        return SimpleNamespace(returncode=0)
    saved = Mock()
    monkeypatch.setattr(job.subprocess, "run", worker)
    monkeypatch.setattr(audit, "save_report", saved)
    job.run_lab_job()
    assert len(calls) == 2
    assert "src.analysis.continuous_lab" in calls[1][0]
    assert saved.call_args.args[0]["status"] == "failed"
