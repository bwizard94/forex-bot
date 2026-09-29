from __future__ import annotations

from datetime import datetime, timezone

from src.analysis.intel import (
    analyze_drivers,
    build_intel_report,
    check_price_consistency,
    compose_stance,
)
from src.analysis.playbook import render_playbook
from src.data.investing import fetch_eurusd_snapshot, parse_snapshot
from src.data.news import Headline, NewsBundle
from src.notifications.slack_bot import intel_blocks

FIXTURE = """
# EUR/USD - Euro US Dollar

Add to Watchlist

1.1475

+0.0010(+0.09%)

Real-time Data·16:15:02

Day's Range

1.1456

1.1498

52 wk Range

1.1325

1.2079

Prev. Close

1.1465

Open

1.1465

1-Year Change

-2.8613%

Bid

1.1474

Ask

1.1476

## Technical Analysis

1 MinUnlock5 MinUnlock15 minUnlock30 MinStrong SellHourlyStrong Sell5 HoursStrong SellDailyStrong SellWeeklyStrong SellMonthlySell

Summary

Strong Sell

## Euro US Dollar Quotes

| Exchange | Last | Bid | Ask | Volume | Chg. % |
| --- | --- | --- | --- | --- | --- |
| Real-time Currencies 16:13:48 | 1.1475 | 1.1474 | 1.1476 | 0 | +0.09% |
| CME 16:03:13 | 1.1519 | 1.1518 | 1.1519 | 11,781 | +0.06% |

## Economic Calendar

[Initial Jobless Claims](https://www.investing.com/economic-calendar/initial-jobless-claims-294)

Act:

196.00K

Cons:

207.00K

Prev.:

206.00K

[Housing Starts (Aug)](https://www.investing.com/economic-calendar/housing-starts-151)

Act:

1.275M

Cons:

1.32M

Prev.:

1.309M

[CPI (YoY) (Aug)](https://www.investing.com/economic-calendar/cpi-68)

Act:

3.20%

Cons:

3.30%

Prev.:

2.90%

[Core CPI (YoY) (Aug)](https://www.investing.com/economic-calendar/core-cpi-317)

Act:

2.40%

Cons:

2.40%

Prev.:

2.50%

[Philadelphia Fed Manufacturing Index (Sep)](https://www.investing.com/economic-calendar/philadelphia-fed-manufacturing-index-236)

Act:

37.80

Cons:

31.30

Prev.:

47.40

[CFTC EUR speculative net positions](https://www.investing.com/economic-calendar/cftc-eur-speculative-positions-1611)

Act:

-

Cons:

-

Prev.:

-42.60K

## News

[Dollar pauses after Fed rally as yields, oil retreat](https://www.investing.com/news/economy-news/hawkish-fed-lifts-dollar-to-sevenweek-high-as-focus-turn-to-boj-4904757)

*   Reuters
*   37 minutes ago

[Fed Delivers Hawkish Hike, Dollar Rallies but Gold Recovers](https://www.investing.com/analysis/fed-delivers-hawkish-hike-dollar-rallies-but-gold-recovers-200687866)

[Touax H1 2026 slides: profit swings to loss despite refinancing wins](https://www.investing.com/news/company-news/touax-h1-2026-slides-profit-swings-to-loss-despite-refinancing-wins-93CH-4905972)

## People Also Watch

[S&P 500 VIX](https://www.investing.com/indices/volatility-s-p-500)

15.44

[Dollar Index](https://www.investing.com/currencies/us-dollar-index)

99.97

[Crude Oil WTI Futures](https://www.investing.com/commodities/crude-oil)

101.31

[Gold Futures](https://www.investing.com/commodities/gold)

4,382.51

## FAQ

### What Is the Current EUR/USD Exchange Rate?

The current EUR/USD exchange rate is 1.1475, with a previous close of 1.1465.

### What Is the Daily Range for EUR/USD?

Today’s EUR/USD range is from 1.1456 to 1.1498.

### What Was the Opening Price for EUR/USD Today?

The opening price for EUR/USD today was 1.1465.

### What Is the Bid and Ask for EUR/USD?

The bid price is 1.1474 and the ask price is 1.1476 for EUR/USD.

### What Is the 52-Week Range for EUR/USD?

The 52-week range for EUR/USD is 1.1325 to 1.2079.

### Is EUR/USD a Buy or Sell Based on Technical Indicators?

Based on technical indicators, EUR/USD is currently rated Strong Sell.
"""


def test_parse_investing_quote_ta_calendar() -> None:
    snap = parse_snapshot(FIXTURE, now=datetime(2026, 9, 17, 20, 20, tzinfo=timezone.utc))
    assert snap.last == 1.1475
    assert snap.daily_pct == 0.09
    assert snap.bid == 1.1474
    assert snap.ask == 1.1476
    assert snap.day_low == 1.1456
    assert snap.day_high == 1.1498
    assert snap.open == 1.1465
    assert snap.prev_close == 1.1465
    assert snap.low_52w == 1.1325
    assert snap.high_52w == 1.2079
    assert snap.year_pct == -2.8613
    assert snap.summary == "Strong Sell"
    assert snap.ta_daily == "Strong Sell"
    assert snap.ta_weekly == "Strong Sell"
    assert snap.ta_hourly == "Strong Sell"
    assert snap.ta_monthly == "Sell"
    assert snap.stacked_sell()
    assert snap.cme_last == 1.1519
    assert snap.claims_k == 196.0
    assert snap.claims_cons_k == 207.0
    assert snap.housing_m == 1.275
    assert snap.ea_cpi == 3.20
    assert snap.ea_core == 2.40
    assert snap.philly == 37.80
    assert snap.cftc_eur_k == -42.60
    assert snap.dxy == 99.97
    assert snap.wti == 101.31
    assert snap.news and "Dollar pauses" in snap.news[0].title
    assert all("Touax" not in item.title for item in snap.news)
    drivers = " ".join(snap.driver_lines())
    assert "Investing.com EUR/USD last" in drivers
    assert "crowded" in drivers.lower() or "day low" in drivers.lower()


def test_cloudflare_challenge_is_empty() -> None:
    snap = parse_snapshot(
        "<html><title>Just a moment...</title><body>Enable JavaScript and cookies to continue</body></html>"
    )
    assert snap.last is None
    assert snap.errors
    assert "Cloudflare" in snap.errors[0]


def test_fetch_failure_is_empty(monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("blocked")

    monkeypatch.setattr("src.data.investing.fetch_page", _boom)
    snap = fetch_eurusd_snapshot()
    assert snap.last is None
    assert "failed" in snap.errors[0].lower()


def test_inv_sixth_print_and_playbook() -> None:
    snap = parse_snapshot(FIXTURE)
    now = datetime(2026, 9, 17, 20, 20, tzinfo=timezone.utc)
    check = check_price_consistency(
        oanda_mid=1.14740,
        cf_mid=1.14730,
        m5_close=1.14740,
        spread=0.00012,
        quote_ts=now,
        warn_pips=8.0,
        now=now,
        inv_mid=snap.last,
    )
    assert check.inv_mid == 1.1475
    assert abs(check.oanda_vs_inv_pips or 0) < 3
    bundle = NewsBundle(headlines=[Headline(title="Fed speakers eyed", source="Yahoo EURUSD")], events=[])
    report = build_intel_report(
        price=check,
        bundle=bundle,
        macro=[],
        h1_bias="bearish",
        d1_bias="bearish",
        now=now,
        inv=snap,
    )
    assert report.inv.get("last") == 1.1475
    assert any("Investing.com" in d for d in report.drivers)
    stance = compose_stance(
        h1_bias="bearish",
        d1_bias="bearish",
        sentiment=-2,
        price=check,
        macro=[],
        inv=snap,
    )
    assert "day low" in stance.lower() or "Strong Sell" in stance
    text = render_playbook(intel=report)
    assert "## Investing.com (EUR/USD)" in text
    assert "desk/INVESTING.md" in text
    assert "1.1519" in text or "Strong Sell" in text
    blocks = str(intel_blocks(report))
    assert "Investing.com" in blocks
    assert "INVESTING.md" in blocks
    drivers = analyze_drivers([], [], [], now=now, inv=snap)
    assert any("CFTC" in d or "CME" in d or "Strong Sell" in d or "claims" in d for d in drivers)
