from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.analysis.intel import IntelReport, PriceCheck
from src.analysis.playbook import MISTAKES_PATH, MT4_PATH, NEWS_PATH, OPS_PATH, SCALP_PATH, SHEETS_PATH, FF_PATH, read_mistakes, read_mt4, read_news, read_operating, read_scalping, read_sheets, render_playbook
from src.config import Settings
from src.notifications.slack_bot import intel_blocks


def test_default_book_is_ox_scalp() -> None:
    assert Settings.model_fields["trading_style"].default == "scalp"
    assert Settings.model_fields["atr_sl_multiplier"].default == 1.0
    assert Settings.model_fields["atr_tp1_multiplier"].default == 1.2
    assert Settings.model_fields["atr_tp2_multiplier"].default == 2.0
    assert Settings.model_fields["risk_per_trade_pct"].default == 0.006
    assert Settings.model_fields["scalp_max_spread_pips"].default == 1.8
    assert Settings.model_fields["scalp_max_hold_minutes"].default == 90
    assert Settings.model_fields["max_trades_per_day"].default == 8
    assert Settings.model_fields["friday_flat_hour"].default == 20
    text = read_scalping()
    assert text
    assert SCALP_PATH.name == "SCALPING.md"
    blob = text.lower()
    assert "lwma" in blob
    assert "trend envelopes" in blob
    assert "dss" in blob
    assert "weekly candlestick" in blob


def test_operating_doctrine_file_names_the_three_sources() -> None:
    text = read_operating()
    assert text
    assert OPS_PATH == Path(OPS_PATH)
    blob = text.lower()
    assert "litefinance" in blob
    assert "dukascopy" in blob
    assert "investopedia" in blob
    assert "ox securities" in blob or "oxsecurities" in blob
    assert "intraday" in blob
    assert "scalp" in blob
    assert "swing" in blob
    assert "dual venue" in blob or "metatrader" in blob
    assert "preserve capital" in blob
    assert "expectancy" in blob
    assert "lwma" in blob or "wma" in blob


def test_mistakes_book_names_the_refusal_codes() -> None:
    text = read_mistakes()
    assert text
    assert MISTAKES_PATH.name == "MISTAKES.md"
    blob = text.lower()
    assert "overtrading" in blob
    assert "weekend" in blob
    assert "martingale" in blob
    assert "slippage" in blob
    assert "kill switch" in blob
    assert "sunday" in blob


def test_playbook_repeats_operating_rules() -> None:
    price = PriceCheck(
        oanda_mid=1.1475,
        cf_mid=1.1474,
        m5_close=1.1474,
        spread_pips=1.0,
        oanda_vs_cf_pips=1.0,
        oanda_vs_m5_pips=1.0,
        stale=False,
        verdict="consistent",
        notes=["ok"],
    )
    intel = IntelReport(
        ts=datetime(2026, 9, 18, 18, 5, tzinfo=timezone.utc),
        price=price,
        macro=[],
        events=[],
        headlines=[],
        sentiment=0,
        sentiment_label="Mixed / two-way",
        drivers=[],
        stance="H1 is bullish — prefer discounted longs, do not chase shorts.",
        notes=["ok"],
        h1_bias="bullish",
        d1_bias="bearish",
    )
    text = render_playbook(intel=intel)
    assert "## How this desk operates" in text
    assert "desk/OPERATING.md" in text
    assert "desk/MISTAKES.md" in text
    assert "desk/SHEETS.md" in text
    assert "desk/NEWS.md" in text
    assert "desk/FOREXFACTORY.md" in text
    assert "desk/MT4.md" in text
    assert "intraday EUR/USD scalp" in text
    assert "preserve capital" in text.lower()
    assert "SCALPING.md" in text
    blocks = str(intel_blocks(intel))
    assert "OPERATING.md" in blocks
    assert "SCALPING.md" in blocks
    assert "MISTAKES.md" in blocks
    sheets = read_sheets()
    assert sheets
    assert SHEETS_PATH.name == "SHEETS.md"
    assert "trades" in sheets.lower()
    news = read_news()
    assert news
    assert NEWS_PATH.name == "NEWS.md"
    assert "newsnow" in news.lower()
    assert "forex factory" in news.lower()
    assert FF_PATH.name == "FOREXFACTORY.md"
    assert "forexfactory.com/market/eurusd" in FF_PATH.read_text(encoding="utf-8").lower()
    mt4 = read_mt4()
    assert mt4
    assert MT4_PATH.name == "MT4.md"
    assert "212100" in mt4
    assert "ledger" in mt4.lower()


def test_sticky_skip_detects_underwater_and_spread() -> None:
    from src.pipeline import is_sticky_skip

    assert is_sticky_skip(
        "Will not add another SELL onto an underwater ticket — wait for it to pay or stop"
    )
    assert is_sticky_skip("Scalp spread 2.4 pips is wider than 1.8 — wait for London/NY compression.")
    assert is_sticky_skip("Trading paused from dashboard")
    assert is_sticky_skip("Max same-side desk positions reached (2 SELL)")
    assert is_sticky_skip(
        "Anti-martingale: will not add another SELL onto an underwater ticket "
        "(no grid, no averaging down). Wait for it to pay 2.0 pips or stop."
    )
    assert is_sticky_skip("Overtrading halt: 8 desk tickets already opened today (cap 8).")
    assert is_sticky_skip("Kill switch: OANDA quote is stale (120s, cap 90s).")
    assert not is_sticky_skip("News blackout: USD CPI in 12 minutes")
    assert not is_sticky_skip(None)


def test_refresh_growth_does_not_call_history(monkeypatch) -> None:
    import inspect

    from src.pipeline import TradingPipeline

    source = inspect.getsource(TradingPipeline.refresh_growth)
    assert "refresh_history" not in source
    assert "study_extra_datasets" not in source
    kick = inspect.getsource(TradingPipeline.kick_history_study)
    assert "background" in kick.lower() or "Thread" in kick
