from __future__ import annotations

from datetime import datetime, timezone

from src.analysis.intel import (
    check_price_consistency,
    compose_stance,
    typical_eurusd_reaction,
)
from src.analysis.playbook import append_learning, read_learning_log, render_playbook
from src.analysis.intel import IntelReport, PriceCheck
from src.notifications.slack_bot import intel_blocks


def test_typical_reaction_maps_cpi_and_nfp() -> None:
    assert "USD" in typical_eurusd_reaction("US CPI m/m")
    assert "Payrolls" in typical_eurusd_reaction("Non-Farm Payrolls")
    assert "ECB" in typical_eurusd_reaction("ECB Deposit Facility Rate")
    assert "oil" in typical_eurusd_reaction("Brent crude slips").lower()


def test_price_agree_is_consistent() -> None:
    now = datetime(2026, 9, 17, 4, 40, tzinfo=timezone.utc)
    check = check_price_consistency(
        oanda_mid=1.15440,
        cf_mid=1.15435,
        m5_close=1.15432,
        spread=0.00012,
        quote_ts=now,
        warn_pips=8.0,
        now=now,
    )
    assert check.verdict == "consistent"
    assert abs(check.oanda_vs_cf_pips or 0) < 1.0


def test_stale_currencyfreaks_daily_print_is_not_a_veto() -> None:
    now = datetime(2026, 9, 18, 19, 50, tzinfo=timezone.utc)
    check = check_price_consistency(
        oanda_mid=1.14875,
        cf_mid=1.14750,
        m5_close=1.14870,
        spread=0.00016,
        quote_ts=now,
        warn_pips=8.0,
        now=now,
        te_mid=1.14867,
        tv_mid=1.14879,
        cf_as_of=datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc),
    )
    assert check.verdict != "disagree"
    blob = " ".join(check.notes).lower()
    assert "stale" in blob or "not a ticket veto" in blob
    stance = compose_stance(
        h1_bias="bearish",
        d1_bias="bearish",
        sentiment=-1,
        price=check,
        macro=[],
    )
    assert "FLAT" not in stance


def test_price_disagree_blocks_new_tickets() -> None:
    now = datetime(2026, 9, 17, 4, 40, tzinfo=timezone.utc)
    check = check_price_consistency(
        oanda_mid=1.15600,
        cf_mid=1.15400,
        m5_close=1.15410,
        spread=0.00010,
        quote_ts=now,
        warn_pips=8.0,
        now=now,
    )
    assert check.verdict == "disagree"
    assert "Do not size" in " ".join(check.notes)


def test_wide_spread_is_watch() -> None:
    now = datetime(2026, 9, 17, 4, 40, tzinfo=timezone.utc)
    check = check_price_consistency(
        oanda_mid=1.15440,
        cf_mid=1.15438,
        m5_close=1.15432,
        spread=0.00040,
        quote_ts=now,
        warn_pips=8.0,
        now=now,
    )
    assert check.verdict == "watch"
    assert check.spread_pips and check.spread_pips >= 3.5


def test_playbook_render_and_learning_log(tmp_path, monkeypatch) -> None:
    import src.analysis.playbook as pb

    monkeypatch.setattr(pb, "DESK_DIR", tmp_path)
    monkeypatch.setattr(pb, "PLAYBOOK_PATH", tmp_path / "EURUSD_PLAYBOOK.md")
    monkeypatch.setattr(pb, "LEARNING_LOG_PATH", tmp_path / "LEARNING_LOG.md")
    price = PriceCheck(
        oanda_mid=1.1544,
        cf_mid=1.1543,
        m5_close=1.1542,
        spread_pips=1.2,
        oanda_vs_cf_pips=1.0,
        oanda_vs_m5_pips=2.0,
        stale=False,
        verdict="consistent",
        notes=["OANDA and CurrencyFreaks agree within 1.0 pips."],
    )
    intel = IntelReport(
        ts=datetime(2026, 9, 17, 4, 45, tzinfo=timezone.utc),
        price=price,
        macro=[],
        events=[],
        headlines=[{"title": "Fed speakers eyed", "source": "Yahoo EURUSD"}],
        sentiment=-1,
        sentiment_label="Mildly bearish",
        drivers=["US CPI tomorrow — hotter than forecast usually bids USD."],
        stance="Primary hunt: EUR/USD shorts with the H1/D1 downtrend.",
        notes=price.notes,
        h1_bias="bearish",
        d1_bias="bearish",
    )
    text = render_playbook(intel=intel, extra_rules=["Never revenge-trade Asia GBP losses."])
    assert "Price integrity" in text
    assert "What can move EUR/USD next" in text
    assert "Never revenge-trade" in text
    assert "Trading Economics" in text
    assert "FXStreet" in text
    assert "Barchart" in text
    assert "Investing.com" in text
    assert "Forex Factory" in text
    assert "TradingView" in text
    assert "How this desk operates" in text
    assert "preserve capital" in text.lower()
    append_learning("Intel cycle", ["Stance: shorts"], ts=intel.ts)
    log = read_learning_log()
    assert "Intel cycle" in log
    assert "Stance: shorts" in log


def test_intel_slack_blocks_name_forex_channel() -> None:
    price = PriceCheck(
        oanda_mid=1.15,
        cf_mid=1.15,
        m5_close=1.15,
        spread_pips=1.0,
        oanda_vs_cf_pips=0.2,
        oanda_vs_m5_pips=0.1,
        stale=False,
        verdict="consistent",
        notes=["ok"],
    )
    intel = IntelReport(
        ts=datetime(2026, 9, 17, 4, 45, tzinfo=timezone.utc),
        price=price,
        macro=[],
        events=[],
        headlines=[{"title": "ECB holds", "source": "ECB"}],
        sentiment=1,
        sentiment_label="Mildly bullish",
        drivers=["No medium/high prints."],
        stance="H1 is flat — only a strong M5 continuation is allowed.",
        notes=["ok"],
    )
    blocks = intel_blocks(intel)
    blob = str(blocks)
    assert "#forex" in blob
    assert "What can move EUR/USD" in blob
    assert "desk/EURUSD_PLAYBOOK.md" in blob
    assert "TRADINGECONOMICS.md" in blob
    assert "FXSTREET.md" in blob
    assert "BARCHART.md" in blob
    assert "INVESTING.md" in blob
    assert "TRADINGVIEW.md" in blob
    assert "OPERATING.md" in blob


def test_compose_stance_h1_flat_uses_d1_as_map() -> None:
    now = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)
    price = check_price_consistency(
        oanda_mid=1.14875,
        cf_mid=1.14870,
        m5_close=1.14870,
        spread=0.00016,
        quote_ts=now,
        warn_pips=8.0,
        now=now,
    )
    stance = compose_stance(
        h1_bias="neutral",
        d1_bias="bearish",
        sentiment=-1,
        price=price,
        macro=[],
    )
    assert "fade M5 rallies" in stance
    assert "FLAT" not in stance


def test_compose_stance_flats_on_disagree() -> None:
    price = PriceCheck(
        oanda_mid=1.16,
        cf_mid=1.14,
        m5_close=1.15,
        spread_pips=1.0,
        oanda_vs_cf_pips=200.0,
        oanda_vs_m5_pips=100.0,
        stale=False,
        verdict="disagree",
        notes=["far apart"],
    )
    stance = compose_stance(
        h1_bias="bearish",
        d1_bias="bearish",
        sentiment=-2,
        price=price,
        macro=[],
    )
    assert stance.startswith("FLAT")
