from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.analysis.news_patterns import (
    classify_headline,
    fingerprint_title,
    ingest_headlines,
    review_news_outcomes,
)
from src.analysis.playbook import NEWS_PATH, read_news
from src.config import reload_settings
from src.data.news import Headline, harvest_eurusd_news, score_sentiment
from src.data.newsnow import parse_newsnow_html
from src.data.storage import init_db, reset_engine, session_scope, upsert_bars


NEWSNOW_HTML = """
<div class="hl " data-id="1324750570">
  <div class="hl__inner"><a class="hll" href="https://c.newsnow.com/A/1324750570?-45874:2477031434" target="_blank">Euro heads for weekly loss against US Dollar on hawkish Fed outlook</a>
  <span class="src src-part" data-pub="FXSTREET">FXstreet</span>
  <span class="time" data-time="1789739299">09:48</span>
  </div>
</div>
<div class="hl " data-id="1324698237">
  <div class="hl__inner"><a class="hll" href="https://c.newsnow.com/A/1324698237?-45874:2477031434">Euro nudges higher above 1.1450 as US yields, oil retreat</a>
  <span class="src src-part" data-pub="FXSTREET">FXstreet</span>
  <span class="time" data-time="1789693434">21:03</span>
  </div>
</div>
"""


def test_news_book_names_the_sources() -> None:
    text = read_news()
    assert text
    assert NEWS_PATH.name == "NEWS.md"
    blob = text.lower()
    assert "newsnow" in blob
    assert "forex factory" in blob
    assert "05:00" in blob
    assert "inflation" in blob
    assert "not a ticket" in blob or "not trade a headline" in blob


def test_parse_newsnow_html_keeps_dated_wires() -> None:
    items = parse_newsnow_html(NEWSNOW_HTML)
    assert len(items) == 2
    assert "hawkish Fed" in items[0].title
    assert items[0].source.startswith("NewsNow")
    assert items[0].published is not None
    assert items[0].published.year == 2026
    assert "oil retreat" in items[1].title


def test_classify_ff_speakers() -> None:
    lagarde = classify_headline("ECB's Lagarde: rates won't move in lockstep with the Fed")
    assert lagarde.category == "ecb"
    warsh = classify_headline("Three words from Kevin Warsh have Wall Street")
    assert warsh.category == "fed"


def test_classify_fed_hawkish_is_bearish() -> None:
    tagged = classify_headline("Euro heads for weekly loss against US Dollar on hawkish Fed outlook")
    assert tagged.category == "fed"
    assert tagged.predicted == "bearish"
    assert "USD" in tagged.reaction or "Fed" in tagged.reaction


def test_yields_retreat_is_bullish() -> None:
    tagged = classify_headline("Euro nudges higher above 1.1450 as US yields, oil retreat")
    assert tagged.category in {"yields", "energy"}
    assert tagged.predicted == "bullish"
    assert score_sentiment("Euro nudges higher above 1.1450 as US yields, oil retreat") >= 1


def test_ingest_and_revisit_marks_a_correct_bearish_call(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "news.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    reset_engine()
    reload_settings()
    init_db()
    start = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)
    later = start + timedelta(hours=1)
    with session_scope() as session:
        upsert_bars(
            session,
            [
                {
                    "symbol": "EUR/USD",
                    "timeframe": "M5",
                    "ts": start,
                    "open": 1.15,
                    "high": 1.151,
                    "low": 1.149,
                    "close": 1.15,
                    "volume": 1,
                    "source": "test",
                    "complete": True,
                },
                {
                    "symbol": "EUR/USD",
                    "timeframe": "M5",
                    "ts": later,
                    "open": 1.148,
                    "high": 1.1485,
                    "low": 1.147,
                    "close": 1.1475,
                    "volume": 1,
                    "source": "test",
                    "complete": True,
                },
            ],
        )
        added = ingest_headlines(
            session,
            [
                Headline(
                    title="Euro heads for weekly loss against US Dollar on hawkish Fed outlook",
                    source="NewsNow/FXSTREET",
                    url="https://c.newsnow.com/A/1",
                    published=start,
                )
            ],
            price=1.15,
            scan_kind="morning",
            now=start,
        )
        assert added == 1
        assert ingest_headlines(session, [
            Headline(title="Euro heads for weekly loss against US Dollar on hawkish Fed outlook", source="dup")
        ], price=1.15, now=start) == 0
        updated = review_news_outcomes(session, now=later + timedelta(minutes=5))
        assert updated >= 1
        from src.data.storage import NewsItem
        from sqlalchemy import select

        row = session.scalar(select(NewsItem))
        assert row is not None
        assert row.category == "fed"
        assert row.predicted == "bearish"
        assert row.move_1h_pips is not None
        assert row.move_1h_pips <= -5
        assert row.verdict == "correct"


def test_fingerprint_is_stable() -> None:
    assert fingerprint_title("  EUR/USD  Rally  ") == fingerprint_title("eur/usd rally")


def test_harvest_eurusd_news_does_not_crash_with_empty_network(monkeypatch) -> None:
    monkeypatch.setattr("src.data.news._rss_items", lambda *a, **k: [])
    monkeypatch.setattr("src.data.newsnow.fetch_newsnow_headlines", lambda limit=80: [
        Headline(title="ECB Lagarde speaks on EUR/USD", source="NewsNow/FXSTREET")
    ])
    monkeypatch.setattr("src.data.forexfactory.fetch_forexfactory_headlines", lambda limit=80: [
        Headline(
            title="ECB's Lagarde: rates won't move in lockstep with the Fed",
            source="Forex Factory EUR/USD",
            url="https://www.forexfactory.com/news/1418920-ecbs-lagarde-rates-wont-move-in-lockstep-with",
        )
    ])
    items = harvest_eurusd_news(limit=5, deep=False)
    assert items
    assert any("ECB" in h.title or "Lagarde" in h.title for h in items)
    assert any(h.source.startswith("Forex Factory") for h in items)

def test_primary_forexfactory_survives_small_limit_and_failure_has_fallback(monkeypatch):
    monkeypatch.setattr("src.data.news._rss_items", lambda *a, **k: [Headline(title="ECB backup report", source="ECB")])
    monkeypatch.setattr("src.data.newsnow.fetch_newsnow_headlines", lambda **k: [])
    monkeypatch.setattr("src.data.forexfactory.fetch_forexfactory_headlines", lambda **k: [Headline(title="Fed primary report", source="Forex Factory EUR/USD")])
    assert harvest_eurusd_news(limit=1)[0].source == "Forex Factory EUR/USD"
    def fail(**kwargs):
        raise RuntimeError("blocked")
    monkeypatch.setattr("src.data.forexfactory.fetch_forexfactory_headlines", fail)
    assert harvest_eurusd_news(limit=1)[0].source == "ECB"
    assert harvest_eurusd_news(limit=0) == []

def test_empty_collection_and_stale_collection_are_visible(monkeypatch):
    from src.data import news
    from datetime import timedelta
    monkeypatch.setattr(news, "_rss_items", lambda *a, **k: [])
    monkeypatch.setattr("src.data.newsnow.fetch_newsnow_headlines", lambda **k: [])
    monkeypatch.setattr("src.data.forexfactory.fetch_forexfactory_headlines", lambda **k: [])
    monkeypatch.setattr(news, "_HARVEST_STATUS", {})
    assert news.harvest_eurusd_news() == []
    assert news.news_source_status()["harvest"]["state"] == "unavailable"
    checked = news.utcnow()
    monkeypatch.setattr(news, "utcnow", lambda: checked + timedelta(minutes=41))
    assert news.news_source_status()["harvest"]["state"] == "stale"
