from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pytest


@pytest.fixture(autouse=True)
def reset_primary_cache(monkeypatch):
    monkeypatch.setattr("src.data.forexfactory._NEWS_CACHE", None)
    monkeypatch.setattr("src.data.forexfactory._RETRY_AFTER", 0.0)
    monkeypatch.setattr("src.data.forexfactory._SOURCE_STATUS", {"state": "pending", "checked_at": None})

from src.analysis.intel import (
    analyze_drivers,
    build_intel_report,
    compose_stance,
)
from src.analysis.playbook import render_playbook
from src.data.forexfactory import (
    PAIR_URL,
    fetch_eurusd_snapshot,
    parse_news_links,
    parse_snapshot,
    slug_to_title,
)
from src.data.news import CalendarEvent, Headline, NewsBundle
from src.notifications.slack_bot import intel_blocks

FIXTURE = """
<html>
<h1 class="market-instrument__name"><span>EUR/USD</span></h1>
<a href="https://www.forexfactory.com/news/1418920-ecbs-lagarde-rates-wont-move-in-lockstep-with">
ECB's Lagarde: rates won't move in lockstep with the Fed
</a>
<a href="https://www.forexfactory.com/news/1418920-ecbs-lagarde-rates-wont-move-in-lockstep-with/hit">hit</a>
https://www.forexfactory.com/news/1418961-the-fed-hasnt-been-this-terse-since-2007
https://www.forexfactory.com/news/1418979-ecbs-nagel-unlikely-to-get-german-nomination-for
https://www.forexfactory.com/news/1418923-ecbs-kazaeks-if-our-baseline-materializes-moving-into
https://www.forexfactory.com/news/1418987-three-words-from-kevin-warsh-have-wall-street
EUR/USD last 1.14852
</html>
"""


def test_slug_to_title_expands_ecb_and_contractions() -> None:
    assert slug_to_title("ecbs-lagarde-rates-wont-move-in-lockstep-with").startswith("ECB's")
    assert "won't" in slug_to_title("ecbs-lagarde-rates-wont-move-in-lockstep-with")
    assert slug_to_title("the-fed-hasnt-been-this-terse-since-2007").startswith("The Fed")
    assert "hasn't" in slug_to_title("the-fed-hasnt-been-this-terse-since-2007")


def test_parse_news_links_dedupes_hit_suffix_and_prefers_anchor() -> None:
    items = parse_news_links(FIXTURE)
    urls = {item.url for item in items}
    assert not any(url.endswith("/hit") for url in urls)
    lagarde = next(item for item in items if "1418920" in item.url)
    assert "lockstep" in lagarde.title.lower()
    assert "Lagarde" in lagarde.title
    assert any("terse" in item.title.lower() for item in items)
    assert any("Nagel" in item.title or "nagel" in item.title.lower() for item in items)
    assert any("Warsh" in item.title or "warsh" in item.title.lower() for item in items)
    assert all(item.source == "Forex Factory EUR/USD" for item in items)


def test_parse_snapshot_reads_news_and_last() -> None:
    snap = parse_snapshot(FIXTURE, url=PAIR_URL, now=datetime(2026, 9, 19, 5, 30, tzinfo=timezone.utc))
    assert snap.last == 1.14852
    assert len(snap.news) >= 4
    drivers = " ".join(snap.driver_lines())
    assert "pair news reference" in drivers
    assert "Lagarde" in drivers or "lockstep" in drivers.lower()


def test_cloudflare_challenge_is_empty() -> None:
    snap = parse_snapshot(
        "<html><title>Just a moment...</title><body>Enable JavaScript and cookies to continue</body></html>"
    )
    assert snap.news == []
    assert snap.last is None
    assert snap.errors
    assert "Cloudflare" in snap.errors[0]


def test_fetch_failure_is_empty(monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("blocked")

    monkeypatch.setattr("src.data.forexfactory.fetch_page", _boom)
    monkeypatch.setattr("src.data.news.fetch_calendar", lambda: [])
    snap = fetch_eurusd_snapshot()
    assert snap.news == []
    assert "failed" in snap.errors[0].lower()


def test_ff_intel_playbook_and_slack() -> None:
    now = datetime(2026, 9, 19, 5, 30, tzinfo=timezone.utc)
    snap = parse_snapshot(FIXTURE, url=PAIR_URL, now=now)
    snap.events = [
        CalendarEvent(
            title="USD CPI YoY",
            country="USD",
            impact="High",
            ts=datetime(2026, 9, 19, 12, 30, tzinfo=timezone.utc),
        )
    ]
    from src.analysis.intel import PriceCheck

    check = PriceCheck(
        oanda_mid=1.1485,
        cf_mid=1.1484,
        m5_close=1.1485,
        spread_pips=1.0,
        oanda_vs_cf_pips=1.0,
        oanda_vs_m5_pips=0.0,
        stale=False,
        verdict="consistent",
        notes=["ok"],
    )
    bundle = NewsBundle(headlines=[Headline(title="Fed speakers eyed", source="Yahoo EURUSD")], events=[])
    report = build_intel_report(
        price=check,
        bundle=bundle,
        macro=[],
        h1_bias="bearish",
        d1_bias="bearish",
        now=now,
        ff=snap,
    )
    assert report.ff.get("last") == 1.14852
    assert any("Forex Factory" in d for d in report.drivers)
    stance = compose_stance(
        h1_bias="bearish",
        d1_bias="bearish",
        sentiment=-1,
        price=check,
        macro=[],
        ff=snap,
    )
    assert "red print" in stance.lower() or "CPI" in stance
    text = render_playbook(intel=report)
    assert "## Forex Factory (EUR/USD market news)" in text
    assert "desk/FOREXFACTORY.md" in text
    assert "lockstep" in text.lower() or "Lagarde" in text
    blocks = str(intel_blocks(report))
    assert "FOREXFACTORY.md" in blocks
    drivers = analyze_drivers([], [], [], now=now, ff=snap)
    assert any("CPI" in d or "red print" in d.lower() or "Forex Factory" in d for d in drivers)

def test_primary_news_filters_unrelated_items_and_never_extracts_quote():
    snap = parse_snapshot(FIXTURE + '<a href="/news/123456-australian-building-approvals-fall">Australian building approvals fall</a>')
    assert snap.last is None
    assert snap.news
    assert not any("Australian" in item.title for item in snap.news)
    assert snap.url == "https://www.forexfactory.com/news"


def test_headline_fetch_rejects_challenge_even_with_news_links(monkeypatch):
    from src.data.forexfactory import fetch_forexfactory_headlines
    monkeypatch.setattr("src.data.forexfactory.fetch_page", lambda: "Just a moment " + FIXTURE)
    assert fetch_forexfactory_headlines() == []
    assert fetch_forexfactory_headlines(limit=0) == []

def test_blocked_source_backs_off_and_recovers(monkeypatch):
    from src.data import forexfactory as ff
    calls = []
    clock = [100.0]
    def fetch(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Forex Factory blocked (403)")
        return FIXTURE
    monkeypatch.setattr(ff, "fetch_page", fetch)
    monkeypatch.setattr(ff.time, "monotonic", lambda: clock[0])
    assert ff.fetch_forexfactory_headlines() == []
    assert ff.source_status()["state"] == "blocked"
    assert ff.fetch_forexfactory_headlines() == []
    assert len(calls) == 1
    clock[0] += ff.FETCH_INTERVAL_SECONDS + 1
    assert ff.fetch_forexfactory_headlines()
    assert ff.source_status()["state"] == "available"
    assert len(calls) == 2


def test_cached_news_isolation_and_stale_diagnostics(monkeypatch):
    from src.data import forexfactory as ff
    from unittest.mock import Mock
    fetch = Mock(return_value=FIXTURE)
    monkeypatch.setattr(ff, "fetch_page", fetch)
    first = ff._fetch_news_snapshot()
    first.news.clear()
    assert ff.fetch_forexfactory_headlines()
    fetch.assert_called_once()
    monkeypatch.setattr(ff, "utcnow", lambda: first.fetched_at + timedelta(minutes=41))
    assert ff.source_status()["state"] == "stale"


def test_health_exposes_news_diagnostics_without_fetching(monkeypatch):
    from types import SimpleNamespace
    from src.dashboard.app import create_app
    from src.data import forexfactory as ff
    monkeypatch.setattr("src.dashboard.app.get_pipeline",
                        lambda: SimpleNamespace(_warm=True, trading_enabled=False))
    monkeypatch.setattr(ff, "_SOURCE_STATUS", {"state": "blocked", "checked_at": None})
    def unexpected(**kwargs):
        raise AssertionError("Health must not fetch the network")
    monkeypatch.setattr(ff, "fetch_page", unexpected)
    health = next(route.endpoint for route in create_app().routes if route.path == "/api/health")
    assert health()["news_sources"]["primary"]["state"] == "blocked"
    assert health()["version"] == "2.22.1"
