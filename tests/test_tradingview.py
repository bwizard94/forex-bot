from __future__ import annotations

from datetime import datetime, timezone

from src.analysis.indicators import compute_indicators, supertrend, session_vwap, wavetrend
from src.analysis.intel import (
    IntelReport,
    PriceCheck,
    analyze_drivers,
    build_intel_report,
    check_price_consistency,
    compose_stance,
)
from src.analysis.playbook import render_playbook
from src.analysis.signals import classify_signal_type
from src.data.news import NewsBundle
from src.data.tradingview import parse_snapshot, parse_quote
from src.notifications.slack_bot import intel_blocks

from tests.test_analysis import _ohlc

QUOTE_FIXTURE = """
<html><body>
<button data-qa-id="market-status-badge-button"><span title="Market closed">closed</span></button>
<script>{"trade":{"price":1.14814},"daily_bar":{"close":"1.14814","high":"1.14826","low":"1.14744","open":"1.14792"}}</script>
<p>The current rate of EURUSD is 1.14810 USD</p>
<p>1 day −0.05% 5 days −1.23% 1 month −0.91% 6 months −1.01% Year to date −2.37% 1 year −2.89% 5 years −2.16% 10 years 2.81% All time 24.92%</p>
<p>The technical rating for the pair is sell today, but don't forget that markets can be very unstable. According to our 1 week rating the EURUSD shows the sell signal, and 1 month rating is neutral.</p>
<p>EURUSD has volatility rating of 0.32%.</p>
<a href="https://www.tradingview.com/chart/EURUSD/ZKHr1LSu-EURUSD-BUY-SETUP">EURUSD BUY SETUP</a>
<p>Buy Zone: 1.1480–1.1510</p>
<a href="https://www.tradingview.com/chart/EURUSD/XvRuVnOo-EURUSD-Bearish-Continuation-Trendline-Breakdown-2H">EURUSD Bearish Continuation</a>
<p>the 1.1580–1.1590 area has turned into an important resistance region. The lower 1.1455 area remains the key support objective.</p>
<a href="https://www.tradingview.com/chart/EURUSD/CVFRLKpB-EURUSD-Resistance-Zone-Rejection-Targets-1-1560-Support">EURUSD Resistance Zone Rejection Targets 1.1560 Support</a>
</body></html>
"""

FIXTURE = """
<html><body>
<a href="https://www.tradingview.com/script/8JLOZcNH-Reaction-Path-BullByte/" data-qa-id="ui-lib-card-link-title">Reaction Path [BullByte]</a>
<a href="https://www.tradingview.com/script/8JLOZcNH-Reaction-Path-BullByte/" data-qa-id="ui-lib-card-link-paragraph"><span class="line-clamp-content-Ubt18o3C">Reaction Path is a price-action, pressure, volatility, and trade-geometry indicator designed to organize two different market behaviours into one integrated framework: 1. Reaction: price has displaced away from its current Fair Price area.</span></a>
<a href="https://www.tradingview.com/script/5qXfyxql-ICT-Setup-05-TradingFinder-Liquidity-Sweep-OB-Retest/" data-qa-id="ui-lib-card-link-title">ICT Setup 05 [TradingFinder] Liquidity Sweep &amp; OB Retest</a>
<a href="https://www.tradingview.com/script/5qXfyxql-ICT-Setup-05-TradingFinder-Liquidity-Sweep-OB-Retest/" data-qa-id="ui-lib-card-link-paragraph"><span class="line-clamp-content-Ubt18o3C">Liquidity sweeps are one of those things traders see all the time. Price can run above a previous high or below a previous low, grab liquidity, and still continue.</span></a>
<a href="https://www.tradingview.com/script/CPcOR9RQ-Strong-GEX-Liquidations-ProjectSyndicate/" data-qa-id="ui-lib-card-link-title">Strong GEX Liquidations | ProjectSyndicate</a>
<a href="https://www.tradingview.com/script/CPcOR9RQ-Strong-GEX-Liquidations-ProjectSyndicate/" data-qa-id="ui-lib-card-link-paragraph"><span class="line-clamp-content-Ubt18o3C">Strong GEX Liquidations maps the one thing a liquidity trader actually wants to see — where over-leveraged positions get force-closed — and prints it as heat.</span></a>
</body></html>
"""


def test_parse_keeps_eurusd_ideas_and_drops_gex() -> None:
    snap = parse_snapshot(FIXTURE, now=datetime(2026, 9, 17, 20, 35, tzinfo=timezone.utc))
    titles = [item.title for item in snap.scripts]
    assert any("Reaction Path" in t for t in titles)
    assert any("Liquidity Sweep" in t for t in titles)
    assert any("GEX" in t for t in titles)
    assert any("Reaction Path" in t for t in snap.kept)
    assert any("Liquidity Sweep" in t for t in snap.kept)
def test_skip_uses_title_not_poisoned_blurb() -> None:
    html = """
    <a data-qa-id="ui-lib-card-link-title">Strong Contrarian Zones | ProjectSyndicate</a>
    <a data-qa-id="ui-lib-card-link-paragraph"><span class="line-clamp-content-x">maps liquidations and GEX heat by mistake</span></a>
    """
    snap = parse_snapshot(html)
    assert any("Contrarian" in t for t in snap.kept)
    assert not any("Contrarian" in t for t in snap.skipped)
    assert "Reaction Path / fair price" in snap.hunt
    drivers = snap.driver_lines()
    assert any("TradingView catalog kept" in line for line in drivers)


def test_challenge_html_is_not_a_catalog() -> None:
    snap = parse_snapshot("<html>Just a moment... cf-chl challenge-platform</html>")
    assert snap.errors
    assert not snap.scripts
    assert snap.hunt


def test_tv_indicators_compute_on_ohlc() -> None:
    df = _ohlc(180, start=1.10, drift=0.00012)
    out = compute_indicators(df)
    last = out.dropna(subset=["supertrend", "vwap", "wt1", "tma", "ewmac"]).iloc[-1]
    assert float(last["supertrend"]) > 0
    assert last["st_dir"] in (1.0, -1.0, 1, -1)
    assert float(last["vwap"]) > 1.0
    assert last["wt1"] == last["wt1"]
    assert "squeeze_on" in out.columns
    st, direction = supertrend(df["high"], df["low"], df["close"])
    assert direction.dropna().iloc[-1] in (1.0, -1.0)
    vwap = session_vwap(df["high"], df["low"], df["close"], df["volume"], df.index)
    assert float(vwap.iloc[-1]) > 0
    wt1, wt2 = wavetrend(df["high"], df["low"], df["close"])
    assert wt1.dropna().shape[0] > 10
    assert wt2.dropna().shape[0] > 5


def test_classify_tv_setup_tags() -> None:
    assert "squeeze" in classify_signal_type("SELL", ["TTM squeeze fire with negative momentum"])
    assert "sweep" in classify_signal_type(
        "SELL", ["Liquidity sweep of prior highs (close back inside Donchian)"]
    )
    assert "supertrend" in classify_signal_type("BUY", ["Supertrend flip to bullish"])
    assert "vwap" in classify_signal_type("BUY", ["Continuation beyond session VWAP (fair price)"])
    assert "wavetrend" in classify_signal_type("BUY", ["WaveTrend bullish cross"])


def test_compose_stance_mentions_tradingview_washout() -> None:
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
    tv = parse_snapshot(FIXTURE)
    stance = compose_stance(
        h1_bias="bearish",
        d1_bias="bearish",
        sentiment=-1,
        price=price,
        macro=[],
        tv=tv,
    )
    assert "TradingView" in stance
    assert "washout" in stance.lower() or "WaveTrend" in stance


def test_playbook_and_slack_include_tradingview() -> None:
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
    tv = parse_snapshot(FIXTURE)
    intel = IntelReport(
        ts=datetime(2026, 9, 17, 20, 35, tzinfo=timezone.utc),
        price=price,
        macro=[],
        events=[],
        headlines=[],
        sentiment=-1,
        sentiment_label="Mildly bearish",
        drivers=["TradingView catalog kept: Reaction Path [BullByte]."],
        stance="Primary hunt: EUR/USD shorts with the H1/D1 downtrend.",
        notes=["ok"],
        h1_bias="bearish",
        d1_bias="bearish",
        tv=tv.as_dict(),
    )
    text = render_playbook(intel=intel)
    assert "## TradingView (scripts)" in text
    assert "tradingview.com/scripts" in text
    assert "desk/TRADINGVIEW.md" in text
    blocks = intel_blocks(intel)
    blob = str(blocks)
    assert "TRADINGVIEW.md" in blob
    report = build_intel_report(
        price=price,
        bundle=NewsBundle(),
        macro=[],
        h1_bias="bearish",
        d1_bias="bearish",
        tv=tv,
    )
    assert report.tv.get("kept")
    assert any("TradingView" in d for d in report.drivers)
    assert any("TradingView catalog kept" in d for d in analyze_drivers([], [], [], tv=tv))


def test_parse_eurusd_quote_reads_last_ratings_and_levels() -> None:
    snap = parse_quote(QUOTE_FIXTURE, now=datetime(2026, 9, 18, 18, 45, tzinfo=timezone.utc))
    assert snap.last == 1.14810
    assert snap.ta_today == "Sell"
    assert snap.ta_week == "Sell"
    assert snap.ta_month == "Neutral"
    assert snap.stacked_sell()
    assert snap.month_neutral()
    assert snap.volatility_pct == 0.32
    assert snap.pct_1d == -0.05
    assert snap.pct_5d == -1.23
    assert snap.pct_1y == -2.89
    assert snap.buy_zone_low == 1.1480
    assert snap.buy_zone_high == 1.1510
    assert snap.support == 1.1455
    assert snap.resistance_low == 1.1580
    assert snap.resistance_high == 1.1590
    assert snap.target_1560 == 1.1560
    assert snap.day_low == 1.14744
    assert snap.day_high == 1.14826
    assert snap.market_closed
    titles = " ".join(item.title for item in snap.ideas)
    assert "BUY SETUP" in titles
    assert "Bearish Continuation" in titles
    drivers = " ".join(snap.driver_lines())
    assert "1.14810" in drivers
    assert "washout" in drivers.lower()
    assert "Neutral" in drivers


def test_quote_challenge_is_not_a_print() -> None:
    snap = parse_quote("<html>Just a moment... cf-chl challenge-platform</html>")
    assert snap.errors
    assert snap.last is None


def test_compose_stance_tv_sell_is_not_a_washout_short() -> None:
    price = PriceCheck(
        oanda_mid=1.14810,
        cf_mid=1.14805,
        m5_close=1.14800,
        spread_pips=1.0,
        oanda_vs_cf_pips=0.5,
        oanda_vs_m5_pips=1.0,
        stale=False,
        verdict="consistent",
        notes=["ok"],
        tv_mid=1.14810,
        oanda_vs_tv_pips=0.0,
    )
    tvq = parse_quote(QUOTE_FIXTURE)
    stance = compose_stance(
        h1_bias="bearish",
        d1_bias="bearish",
        sentiment=-1,
        price=price,
        macro=[],
        tvq=tvq,
    )
    assert "TradingView technicals" in stance
    assert "washout" in stance.lower()
    assert "not a new downtrend" in stance
    assert "Crowd BUY" in stance


def test_playbook_and_slack_include_tv_quote() -> None:
    price = PriceCheck(
        oanda_mid=1.14810,
        cf_mid=1.14805,
        m5_close=1.14800,
        spread_pips=1.0,
        oanda_vs_cf_pips=0.5,
        oanda_vs_m5_pips=1.0,
        stale=False,
        verdict="consistent",
        notes=["ok"],
        tv_mid=1.14810,
        oanda_vs_tv_pips=0.0,
    )
    tvq = parse_quote(QUOTE_FIXTURE)
    intel = IntelReport(
        ts=datetime(2026, 9, 18, 18, 45, tzinfo=timezone.utc),
        price=price,
        macro=[],
        events=[],
        headlines=[],
        sentiment=-1,
        sentiment_label="Mildly bearish",
        drivers=tvq.driver_lines(),
        stance="Primary hunt: EUR/USD shorts with the H1/D1 downtrend.",
        notes=["ok"],
        h1_bias="bearish",
        d1_bias="bearish",
        tvq=tvq.as_dict(),
    )
    text = render_playbook(intel=intel)
    assert "## TradingView (EURUSD hub)" in text
    assert "tradingview.com/symbols/EURUSD" in text
    assert "1.14810" in text
    assert "seventh print" in text.lower()
    blocks = intel_blocks(intel)
    blob = str(blocks)
    assert "TradingView" in blob
    assert "1.14810" in blob
    report = build_intel_report(
        price=price,
        bundle=NewsBundle(),
        macro=[],
        h1_bias="bearish",
        d1_bias="bearish",
        tvq=tvq,
    )
    assert report.tvq.get("last") == 1.14810
    assert any("TradingView EURUSD last" in d for d in report.drivers)


def test_price_check_seventh_print_is_context() -> None:
    now = datetime(2026, 9, 18, 18, 45, tzinfo=timezone.utc)
    check = check_price_consistency(
        oanda_mid=1.14810,
        cf_mid=1.14805,
        m5_close=1.14800,
        spread=0.00012,
        quote_ts=now,
        warn_pips=8.0,
        now=now,
        tv_mid=1.14810,
    )
    assert check.tv_mid == 1.14810
    assert check.oanda_vs_tv_pips == 0.0
    assert any("TradingView last" in n for n in check.notes)
    far = check_price_consistency(
        oanda_mid=1.14810,
        cf_mid=1.14805,
        m5_close=1.14800,
        spread=0.00012,
        quote_ts=now,
        warn_pips=8.0,
        now=now,
        tv_mid=1.14920,
    )
    assert far.verdict == "consistent"
    assert any("Seventh print" in n for n in far.notes)
