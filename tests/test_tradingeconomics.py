from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.analysis.intel import (
    PriceCheck,
    analyze_drivers,
    build_intel_report,
    check_price_consistency,
    compose_stance,
    typical_eurusd_reaction,
)
from src.analysis.playbook import render_playbook
from src.data.news import Headline, NewsBundle
from src.data.tradingeconomics import fetch_eurusd_snapshot, parse_snapshot
from src.notifications.slack_bot import intel_blocks

FIXTURE = """
<html>
<head>
<meta name="description" content="The EUR/USD exchange rate rose to 1.1478 on September 17, 2026, up 0.12% from the previous session. Over the past month, the Euro US Dollar Exchange Rate - EUR/USD has weakened 0.84%, and is down by 2.63% over the last 12 months." />
<script>TEForecast =   [1.16,1.17,1.18,1.18]; TEChartsMeta = [{"value":1.147920000000,"symbol":"EURUSD:CUR"}];</script>
</head>
<body>
<div class="row">
  <div class="market-header-value">
    <div class="te-market-header">Exchange Rate</div>
    <span id="market_last">1.14792</span>
  </div>
  <div class="market-header-value">
    <div class="te-market-header">Daily Change</div>
    <span id="market_daily_chg">0.0014</span>
    <span id="market_daily_Pchg">0.12%</span>
  </div>
  <div class="market-header-value">
    <div class="te-market-header">Monthly</div>
    <span style="color: #ed3b3b;">-0.83%</span>
  </div>
  <div class="market-header-value">
    <div class="te-market-header">Yearly</div>
    <span style="color: #ed3b3b;">-2.62%</span>
  </div>
  <div class="market-header-value">
    <div class="te-market-header">Q3 Forecast</div>
    <span>1.16092</span>
  </div>
</div>
<div id="historical-desc">
  <h2 id="description">The euro traded just below $1.15, remaining at its weakest level since late July, as the dollar strengthened after the Federal Reserve raised interest rates yesterday and signalled another hike later this year.</h2>
</div>
<div id="forecast-desc" class="tab-pane card">
  <div class="card-header">Euro US Dollar Exchange Rate - EUR/USD - Forecast</div>
  <div class="card-body">
    <h3>The Euro US Dollar Exchange Rate - EUR/USD is expected to trade at 1.16 by the end of this quarter, according to Trading Economics global macro models and analysts expectations. Looking forward, we estimate it to trade at 1.18 in 12 months time.</h3>
  </div>
</div>
<table>
  <tr data-symbol="EURUSD:CUR">
    <td><b>EURUSD</b></td>
    <td id="p">1.1479 </td>
    <td></td>
    <td id="nch">0.0014</td>
    <td id="pch">0.12%</td>
    <td>-2.62%</td>
  </tr>
  <tr data-symbol="EURGBP:CUR">
    <td><b>EURGBP</b></td>
    <td id="p">0.8593 </td>
    <td></td>
    <td id="nch">0.0025</td>
    <td id="pch">0.30%</td>
    <td>-1.19%</td>
  </tr>
  <tr data-symbol="EURJPY:CUR">
    <td><b>EURJPY</b></td>
    <td id="p">179.0450 </td>
    <td></td>
    <td id="nch">-0.1030</td>
    <td id="pch">-0.06%</td>
    <td>2.70%</td>
  </tr>
</table>
<table>
  <tr>
    <td><a href="/euro-area/inflation-cpi">Euro Area Inflation Rate</a></td>
    <td>3.20</td><td>2.90</td><td>percent</td><td>Aug 2026</td>
  </tr>
  <tr>
    <td><a href="/united-states/inflation-cpi">United States Inflation Rate</a></td>
    <td>3.40</td><td>3.40</td><td>percent</td><td>Aug 2026</td>
  </tr>
  <tr>
    <td><a href="/united-states/interest-rate">United States Fed Funds Interest Rate</a></td>
    <td>4.00</td><td>3.75</td><td>percent</td><td>Sep 2026</td>
  </tr>
  <tr>
    <td><a href="/euro-area/interest-rate">Euro Area Interest Rate</a></td>
    <td>2.65</td><td>2.40</td><td>percent</td><td>Sep 2026</td>
  </tr>
  <tr>
    <td><a href="/united-states/non-farm-payrolls">United States Non Farm Payrolls</a></td>
    <td>162.00</td><td>21.00</td><td>Thousand</td><td>Aug 2026</td>
  </tr>
</table>
<a href="/euro-area/currency/news/584471"><b>Euro Holds Near Two-Month Low as Fed, ECB Rate Bets Rise</b></a>
2026-09-17
<a href="/euro-area/currency/news/584175">Euro Holds Near One-Month Low Ahead of Fed Decision</a>
2026-09-16
</body>
</html>
"""


def test_parse_te_page_quote_forecast_and_related() -> None:
    snap = parse_snapshot(FIXTURE, now=datetime(2026, 9, 17, 19, 40, tzinfo=timezone.utc))
    assert snap.last == 1.14792
    assert snap.daily_change == 0.0014
    assert snap.daily_pct == 0.12
    assert snap.monthly_pct == -0.83
    assert snap.yearly_pct == -2.62
    assert snap.quarter_forecast == 1.16092
    assert snap.year_forecast == 1.18
    assert snap.forecasts == [1.16, 1.17, 1.18, 1.18]
    assert "weakest level since late July" in snap.summary
    names = {item.name: item for item in snap.related}
    assert names["Euro Area Inflation Rate"].last == 3.2
    assert names["United States Fed Funds Interest Rate"].last == 4.0
    assert names["Euro Area Interest Rate"].last == 2.65
    spread = snap.policy_spread_note() or ""
    assert "1.35" in spread or "+1.35" in spread
    crosses = {item.symbol: item for item in snap.crosses}
    assert crosses["EURUSD"].last == 1.1479
    assert crosses["EURGBP"].day_pct == 0.30
    assert snap.news[0].title.startswith("Euro Holds Near Two-Month Low")
    drivers = " ".join(snap.driver_lines())
    assert "Trading Economics EUR/USD last" in drivers
    assert "weaker euro" in drivers


def test_parse_real_saved_html() -> None:
    path = Path("/home/ubuntu/.cursor/projects/workspace/agent-tools/9166e5b4-2e95-4590-ac25-38f33cb606fe.txt")
    if not path.exists():
        return
    snap = parse_snapshot(path.read_text(encoding="utf-8", errors="ignore"))
    assert snap.last is not None
    assert 1.14 < snap.last < 1.16
    assert snap.daily_pct is not None
    assert snap.quarter_forecast is not None


def test_fetch_failure_is_empty(monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("blocked")

    monkeypatch.setattr("src.data.tradingeconomics.fetch_page", _boom)
    snap = fetch_eurusd_snapshot()
    assert snap.last is None
    assert snap.errors
    assert "failed" in snap.errors[0].lower()


def test_te_third_print_notes_cf_outlier() -> None:
    now = datetime(2026, 9, 17, 19, 40, tzinfo=timezone.utc)
    check = check_price_consistency(
        oanda_mid=1.14880,
        cf_mid=1.14700,
        m5_close=1.14880,
        spread=0.00015,
        quote_ts=now,
        warn_pips=8.0,
        now=now,
        te_mid=1.14792,
    )
    blob = " ".join(check.notes)
    assert check.verdict == "disagree"
    assert "CurrencyFreaks is the outlier" in blob
    assert check.te_mid == 1.14792


def test_oil_reaction_and_te_stance() -> None:
    assert "oil" in typical_eurusd_reaction("Brent crude oil prices jump").lower()
    price = PriceCheck(
        oanda_mid=1.1479,
        cf_mid=1.1478,
        m5_close=1.1479,
        spread_pips=1.2,
        oanda_vs_cf_pips=1.0,
        oanda_vs_m5_pips=0.0,
        stale=False,
        verdict="consistent",
        notes=["ok"],
        te_mid=1.14792,
        oanda_vs_te_pips=-0.2,
    )
    te = parse_snapshot(FIXTURE)
    stance = compose_stance(
        h1_bias="bearish",
        d1_bias="bearish",
        sentiment=-2,
        price=price,
        macro=[],
        te=te,
    )
    assert "shorts" in stance.lower()
    assert "weaker euro" in stance or "1.16" in stance


def test_intel_report_and_playbook_include_te() -> None:
    te = parse_snapshot(FIXTURE)
    now = datetime(2026, 9, 17, 19, 40, tzinfo=timezone.utc)
    price = check_price_consistency(
        oanda_mid=1.14790,
        cf_mid=1.14788,
        m5_close=1.14790,
        spread=0.00012,
        quote_ts=now,
        warn_pips=8.0,
        now=now,
        te_mid=te.last,
    )
    bundle = NewsBundle(
        headlines=[Headline(title="Fed speakers eyed", source="Yahoo EURUSD")],
        events=[],
    )
    report = build_intel_report(
        price=price,
        bundle=bundle,
        macro=[],
        h1_bias="bearish",
        d1_bias="bearish",
        now=now,
        te=te,
    )
    assert report.te.get("last") == 1.14792
    assert any("Trading Economics" in d for d in report.drivers)
    assert report.headlines[0]["source"] == "Trading Economics EUR/USD"
    text = render_playbook(intel=report)
    assert "## Trading Economics (euro-area currency)" in text
    assert "1.14792" in text
    assert "desk/TRADINGECONOMICS.md" in text
    blocks = str(intel_blocks(report))
    assert "Trading Economics" in blocks
    drivers = analyze_drivers([], [], [], now=now, te=te)
    assert any("policy spread" in d.lower() or "Fed funds" in d for d in drivers)
