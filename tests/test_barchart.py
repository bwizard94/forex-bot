from __future__ import annotations

from datetime import datetime, timezone

from src.analysis.intel import (
    analyze_drivers,
    build_intel_report,
    check_price_consistency,
    compose_stance,
)
from src.analysis.playbook import render_playbook
from src.data.barchart import fetch_eurusd_snapshot, parse_snapshot
from src.data.news import Headline, NewsBundle
from src.notifications.slack_bot import intel_blocks

FIXTURE = """
# Euro/U.S. Dollar (^EURUSD)

1.14799 +0.00159 (+0.14%) 14:51 CT [FOREX]

1.14796 x N/A 1.14801 x N/A

Quote Overview for Thu, Sep 17th, 2026

Day Low

1.14565

Day High

1.14977

Open 1.14642

Previous Close 1.14640 1.14640

YTD High 1.20806 1.20806

YTD Low 1.13246 1.13246

Weighted Alpha -2.40 -2.40

Relative Strength 35.07 (+2.89) 35.07

5-Day Change -0.01334 (-1.15%) -0.01334 (-1.15%)

52-Week High 1.20806 (-4.99%) 1.20806

52-Week Low 1.13246 (+1.36%) 1.13246

#### Euro/U.S. Dollar Futures Market News and Commentary

[Dollar Slightly Lower as T-Note Yields Fall](https://www.barchart.com/story/news/4666042/dollar-slightly-lower-as-t-note-yields-fall)

Barchart - 24 minutes ago

The dollar index (DXY00) fell from a new 1.5-month high on Thursday and finished down by -0.03%. Dollar losses were limited Thursday after US weekly jobless claims unexpectedly fell to an 8-week low of 196,000.

#### Commitment of Traders Positions as of Sep 8, 2026

Commercials - Long / Short

593,162 (+59,242)

586,432 (+43,785)

Non-Commercials - Long / Short

198,509 (-4,968)

241,125 (+12,723)

Dealers / Intermediary - Long / Short

54,357 (-286)

315,811 (-6,410)

Asset / Manager - Long / Short

484,443 (+16,189)

233,765 (+28,764)

Leveraged Funds - Long / Short

94,808 (-1,329)

128,093 (-6,217)

Other Reportables - Long / Short

24,587 (+737)

16,412 (+1,408)

#### Price Performance

| Period | Period Low | Period High | Performance |
| --- | --- | --- | --- |
| 1-Month | 1.14565 +0.19% on 09/17/26 | Period Open: 1.15805 | 1.17113 -1.99% on 08/21/26 | -0.01022 (-0.88%) since 08/17/26 |
| 3-Month | 1.13246 +1.36% on 06/24/26 | Period Open: 1.15017 | 1.17113 -1.99% on 08/21/26 | -0.00234 (-0.20%) since 06/17/26 |
| 52-Week | 1.13246 +1.36% on 06/24/26 | Period Open: 1.18132 | 1.20806 -4.99% on 01/27/26 | -0.03349 (-2.83%) since 09/17/25 |

### Barchart Technical Opinion

[Strong sell](https://www.barchart.com/forex/quotes/%5EEURUSD/opinion)

The Barchart Technical Opinion rating is a **72% Sell** with a **Average short term outlook** on maintaining the current direction.

Long term indicators fully support a continuation of the trend.

### Related instruments

| Symbol | Latest | 3M %Chg |
| --- | --- | --- |
| [^EURUSD](https://www.barchart.com/forex/quotes/%5EEURUSD) | 1.14799 | -0.20% |
| [$DXY](https://www.barchart.com/stocks/quotes/$DXY) | 100.21 | -0.14% |
| [FXE](https://www.barchart.com/etfs-funds/quotes/FXE) | 105.92 | -0.15% |
| [E6Z26](https://www.barchart.com/futures/quotes/E6Z26) | 1.15200 | -0.88% |

### Key Turning Points

|     |     |
| --- | --- |
| 3rd Resistance Point | 1.16220 |
| 2nd Resistance Point | 1.15893 |
| 1st Resistance Point | 1.15266 |
| Last Price | 1.14799 |
| 1st Support Level | 1.14312 |
| 2nd Support Level | 1.13985 |
| 3rd Support Level | 1.13358 |

|     |     |
| --- | --- |
| 52-Week High | 1.20806 |
| Fibonacci 61.8% | 1.17918 |
| Fibonacci 50% | 1.17026 |
| Fibonacci 38.2% | 1.16134 |
| Last Price | 1.14799 |
| 52-Week Low | 1.13246 |
"""


def test_parse_barchart_quote_pivots_cot() -> None:
    snap = parse_snapshot(FIXTURE, now=datetime(2026, 9, 17, 20, 10, tzinfo=timezone.utc))
    assert snap.last == 1.14799
    assert snap.daily_pct == 0.14
    assert snap.bid == 1.14796
    assert snap.ask == 1.14801
    assert snap.day_low == 1.14565
    assert snap.day_high == 1.14977
    assert snap.open == 1.14642
    assert snap.high_52w == 1.20806
    assert snap.high_52w_pct == -4.99
    assert snap.low_52w == 1.13246
    assert snap.weighted_alpha == -2.40
    assert snap.relative_strength == 35.07
    assert snap.five_day_pct == -1.15
    assert snap.opinion == "Strong Sell"
    assert snap.opinion_pct == 72.0
    assert snap.opinion_side == "Sell"
    assert snap.r1 == 1.15266
    assert snap.s1 == 1.14312
    assert snap.s3 == 1.13358
    assert snap.fib_618 == 1.17918
    assert snap.fib_50 == 1.17026
    assert snap.fib_382 == 1.16134
    assert snap.perf_1m == -0.88
    assert snap.perf_3m == -0.20
    assert snap.perf_52w == -2.83
    assert snap.dxy == 100.21
    assert snap.fxe == 105.92
    assert snap.euro_fx_fut == 1.15200
    specs = snap.cot_named("Non-Commercials")
    assert specs is not None
    assert specs.long == 198509
    assert specs.short == 241125
    assert snap.specs_net() == 198509 - 241125
    lev = snap.cot_named("Leveraged Funds")
    assert lev is not None and lev.net() is not None and lev.net() < 0
    assert snap.news and "Dollar Slightly Lower" in snap.news[0].title
    drivers = " ".join(snap.driver_lines())
    assert "Barchart ^EURUSD last" in drivers
    assert "1.14312" in drivers
    assert "crowded short" in drivers
    assert not snap.near_day_low(10)
    assert snap.near_day_low(30)


def test_cloudfront_challenge_is_empty() -> None:
    snap = parse_snapshot(
        "<html><title>Access Denied</title><body>Generated by cloudfront Request blocked</body></html>"
    )
    assert snap.last is None
    assert snap.errors
    assert "CloudFront" in snap.errors[0] or "challenge" in snap.errors[0].lower()


def test_fetch_failure_is_empty(monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("blocked")

    monkeypatch.setattr("src.data.barchart.fetch_page", _boom)
    snap = fetch_eurusd_snapshot()
    assert snap.last is None
    assert "failed" in snap.errors[0].lower()


def test_bc_fifth_print_and_playbook() -> None:
    snap = parse_snapshot(FIXTURE)
    now = datetime(2026, 9, 17, 20, 10, tzinfo=timezone.utc)
    check = check_price_consistency(
        oanda_mid=1.14790,
        cf_mid=1.14780,
        m5_close=1.14790,
        spread=0.00012,
        quote_ts=now,
        warn_pips=8.0,
        now=now,
        bc_mid=snap.last,
    )
    assert check.bc_mid == 1.14799
    assert abs(check.oanda_vs_bc_pips or 0) < 3
    bundle = NewsBundle(headlines=[Headline(title="Fed speakers eyed", source="Yahoo EURUSD")], events=[])
    report = build_intel_report(
        price=check,
        bundle=bundle,
        macro=[],
        h1_bias="bearish",
        d1_bias="bearish",
        now=now,
        bc=snap,
    )
    assert report.bc.get("last") == 1.14799
    assert any("Barchart" in d for d in report.drivers)
    stance = compose_stance(
        h1_bias="bearish",
        d1_bias="bearish",
        sentiment=-2,
        price=check,
        macro=[],
        bc=snap,
    )
    assert "day low" in stance.lower() or "S1" in stance
    text = render_playbook(intel=report)
    assert "## Barchart (^EURUSD)" in text
    assert "desk/BARCHART.md" in text
    assert "1.14312" in text
    blocks = str(intel_blocks(report))
    assert "Barchart" in blocks
    assert "BARCHART.md" in blocks
    drivers = analyze_drivers([], [], [], now=now, bc=snap)
    assert any("S1" in d or "crowded" in d or "72%" in d or "Strong Sell" in d for d in drivers)
