from __future__ import annotations

from datetime import datetime, timezone

from src.analysis.intel import (
    analyze_drivers,
    build_intel_report,
    check_price_consistency,
    compose_stance,
)
from src.analysis.playbook import render_playbook
from src.data.fxstreet import fetch_eurusd_snapshot, parse_snapshot
from src.data.news import Headline, NewsBundle
from src.notifications.slack_bot import intel_blocks

FIXTURE = """
# EUR/USD Forecast and News

EUR/USD trades modestly higher on Thursday as falling Oil prices pull US Treasury yields away from their recent highs, prompting the US Dollar to trim part of its post-Fed gains. At the time of writing, the pair trades around 1.1492, up 0.24% on the day, hovering near levels last seen on July 31.

### Technical Analysis

EUR/USD

In the daily chart, EUR/USD keeps a bearish near-term bias as spot holds below all major reference lines. The 100-day simple moving average (SMA), together with the Bollinger Bands (20, 2) middle band sits overhead and suggests the pair remains under broader downside pressure, while even the lower Bollinger band now acts as initial resistance. The Relative Strength Index (14) at 32.29 hovers near oversold territory, hinting that while selling momentum is stretched, bears still control the short-term structure.

On the topside, immediate resistance is located at the former lower Bollinger band near 1.1485, followed by the 100-day SMA at 1.1550, which reinforces the idea of a capped recovery if price attempts a bounce. Above there, the Bollinger middle band at 1.1605 and the upper band at 1.1720 mark subsequent resistance layers.

### Fundamental Analysis

West Texas Intermediate (WTI) Oil trades around $95.50, down nearly 2% on the day, as Saudi Arabia’s rerouting efforts ease supply concerns. The benchmark 10-year US Treasury yield falls to around 4.94%. According to the CME FedWatch Tool, traders see around a 50% chance of another rate increase in October. Initial Jobless Claims fell to 196K from 206K, beating market expectations of 208K. The US Dollar Index (DXY), which tracks the Greenback's value against a basket of six major currencies, trades around 100.08 after touching an intraday high of 100.37. On the Euro side, final August inflation data showed that headline HICP was revised slightly lower to 3.2% annually, while core inflation held at 2.4%. ECB Governing Council member Gabriel Makhlouf said on Thursday “Risks to inflation remain on the upside.”

### 1 Week

: 33%
Bullish
: 67%
Bearish
: 0%
Sideways

: 21%
Bullish
: 43%
Bearish
: 36%
Sideways

### 1 Quarter

: 60%
Bullish
: 27%
Bearish
: 13%
Sideways

Updated Sep 11, 15:00 GMT See full study

### About EUR/USD
The EUR/USD (or Euro Dollar) currency pair belongs to the group of 'Majors'.
"""


def test_parse_fxstreet_last_ta_and_polls() -> None:
    snap = parse_snapshot(FIXTURE, now=datetime(2026, 9, 17, 19, 55, tzinfo=timezone.utc))
    assert snap.last == 1.1492
    assert snap.daily_pct == 0.24
    assert snap.bias == "bearish"
    assert snap.rsi == 32.29
    names = {item.name: item.price for item in snap.resistance}
    assert names["former lower BB"] == 1.1485
    assert names["100-day SMA"] == 1.1550
    assert names["BB middle"] == 1.1605
    assert names["BB upper"] == 1.1720
    assert snap.wti == 95.50
    assert snap.us10y == 4.94
    assert snap.dxy == 100.08
    assert snap.dxy_high == 100.37
    assert snap.fedwatch_oct_pct == 50.0
    assert snap.claims_k == 196.0
    assert snap.hicp == 3.2
    assert snap.core_hicp == 2.4
    polls = {item.horizon: item for item in snap.polls}
    assert polls["1 Week"].bearish == 67.0
    assert polls["1 Week"].bullish == 33.0
    assert polls["1 Month"].bearish == 43.0
    assert polls["1 Quarter"].bullish == 60.0
    drivers = " ".join(snap.driver_lines())
    assert "FXStreet EUR/USD last" in drivers
    assert "lower-band bounce" in drivers


def test_cloudflare_challenge_is_empty() -> None:
    snap = parse_snapshot("<html><title>Just a moment...</title><body>Enable JavaScript and cookies to continue</body></html>")
    assert snap.last is None
    assert snap.errors
    assert "Cloudflare" in snap.errors[0]


def test_fetch_failure_is_empty(monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("blocked")

    monkeypatch.setattr("src.data.fxstreet.fetch_page", _boom)
    snap = fetch_eurusd_snapshot()
    assert snap.last is None
    assert "failed" in snap.errors[0].lower()


def test_fxs_fourth_print_and_playbook() -> None:
    te_like = parse_snapshot(FIXTURE)
    now = datetime(2026, 9, 17, 19, 55, tzinfo=timezone.utc)
    check = check_price_consistency(
        oanda_mid=1.14900,
        cf_mid=1.14890,
        m5_close=1.14900,
        spread=0.00012,
        quote_ts=now,
        warn_pips=8.0,
        now=now,
        fxs_mid=te_like.last,
    )
    assert check.fxs_mid == 1.1492
    assert abs(check.oanda_vs_fxs_pips or 0) < 3
    bundle = NewsBundle(headlines=[Headline(title="Fed speakers eyed", source="Yahoo EURUSD")], events=[])
    report = build_intel_report(
        price=check,
        bundle=bundle,
        macro=[],
        h1_bias="bearish",
        d1_bias="bearish",
        now=now,
        fxs=te_like,
    )
    assert report.fxs.get("last") == 1.1492
    assert any("FXStreet" in d for d in report.drivers)
    stance = compose_stance(
        h1_bias="bearish",
        d1_bias="bearish",
        sentiment=-2,
        price=check,
        macro=[],
        fxs=te_like,
    )
    assert "lower-band bounce" in stance
    text = render_playbook(intel=report)
    assert "## FXStreet (EUR/USD forecast and news)" in text
    assert "desk/FXSTREET.md" in text
    assert "1.1485" in text
    blocks = str(intel_blocks(report))
    assert "FXStreet" in blocks
    assert "FXSTREET.md" in blocks
    drivers = analyze_drivers([], [], [], now=now, fxs=te_like)
    assert any("FedWatch" in d or "resistance" in d for d in drivers)
