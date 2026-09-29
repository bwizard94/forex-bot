"""EUR/USD headlines and high-impact calendar events.

Sources are public (Forex Factory EUR/USD market hub + week JSON, Yahoo
EURUSD RSS, ECB/Fed press RSS, NewsNow). Failures are swallowed so a
dead feed never blocks the desk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree as ET

import requests
from loguru import logger

from src.utils import parse_iso, utcnow

FF_CALENDAR = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
YAHOO_EURUSD = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=EURUSD=X&region=US&lang=en-US"
ECB_RSS = "https://www.ecb.europa.eu/rss/press.html"
FED_RSS = "https://www.federalreserve.gov/feeds/press_all.xml"
GOOGLE_EURUSD = (
    "https://news.google.com/rss/search?q=%22EUR/USD%22+OR+EURUSD&hl=en-US&gl=US&ceid=US:en"
)
GOOGLE_POLICY = (
    "https://news.google.com/rss/search?q=ECB+OR+Lagarde+OR+FOMC+OR+%22Federal+Reserve%22"
    "+euro+dollar&hl=en-US&gl=US&ceid=US:en"
)

EUR_USD_COUNTRIES = {"EUR", "USD", "EMU", "EU", "GER", "USA", "US"}
HIGH_WORDS = {"high", "red", "3"}
MED_WORDS = {"medium", "orange", "2"}

BULLISH_EURUSD = (
    "dovish fed",
    "rate cut",
    "cuts rates",
    "weaker dollar",
    "dollar slides",
    "dollar weak",
    "dollar softness",
    "dollar weakness",
    "hawkish ecb",
    "ecb hike",
    "euro rallies",
    "euro gains",
    "euro nudges higher",
    "risk-on",
    "soft cpi",
    "soft inflation",
    "weak nfp",
    "payrolls miss",
    "yields retreat",
    "yields fall",
    "oil retreat",
)
BEARISH_EURUSD = (
    "hawkish fed",
    "hawkish outlook",
    "fomc hike",
    "stronger dollar",
    "dollar rallies",
    "dollar surge",
    "dovish ecb",
    "ecb cut",
    "euro slides",
    "euro heads for weekly loss",
    "losing streak",
    "risk-off",
    "hot cpi",
    "hot inflation",
    "strong nfp",
    "payrolls beat",
    "yields jump",
    "yields rise",
    "bearish bias",
    "break below",
    "technical slide",
)


@dataclass(slots=True)
class CalendarEvent:
    title: str
    country: str
    impact: str
    ts: datetime | None
    forecast: str = ""
    previous: str = ""
    actual: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "country": self.country,
            "impact": self.impact,
            "ts": self.ts.isoformat() if self.ts else None,
            "forecast": self.forecast,
            "previous": self.previous,
            "actual": self.actual,
        }


@dataclass(slots=True)
class Headline:
    title: str
    source: str
    url: str = ""
    published: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "published": self.published.isoformat() if self.published else None,
        }


@dataclass
class NewsBundle:
    events: list[CalendarEvent] = field(default_factory=list)
    headlines: list[Headline] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _get(url: str, timeout: int = 12) -> requests.Response:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "ForexSentinel/1.4 EURUSD-desk"},
    )
    response.raise_for_status()
    return response


def _parse_when(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    text = str(value).strip()
    try:
        return parse_iso(text)
    except Exception:
        pass
    try:
        return parsedate_to_datetime(text)
    except Exception:
        return None


def _impact(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text in HIGH_WORDS or "high" in text:
        return "High"
    if text in MED_WORDS or "medium" in text:
        return "Medium"
    if "low" in text or text in {"1", "yellow"}:
        return "Low"
    return text.title() or "Unknown"


def _relevant_country(country: str) -> bool:
    token = (country or "").upper().replace(".", "")
    return any(token == c or token.startswith(c) for c in EUR_USD_COUNTRIES)


def fetch_calendar() -> list[CalendarEvent]:
    payload = _get(FF_CALENDAR).json()
    rows = payload if isinstance(payload, list) else payload.get("events") or payload.get("calendar") or []
    events: list[CalendarEvent] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        country = str(row.get("country") or row.get("currency") or "")
        if not _relevant_country(country):
            continue
        title = str(row.get("title") or row.get("event") or "").strip()
        if not title:
            continue
        ts = _parse_when(row.get("date") or row.get("datetime") or row.get("time"))
        events.append(
            CalendarEvent(
                title=title,
                country=country.upper(),
                impact=_impact(row.get("impact") or row.get("volatility")),
                ts=ts,
                forecast=str(row.get("forecast") or ""),
                previous=str(row.get("previous") or ""),
                actual=str(row.get("actual") or ""),
            )
        )
    events.sort(key=lambda e: e.ts or datetime.max.replace(tzinfo=timezone.utc))
    return events


def _rss_items(url: str, source: str, limit: int = 8) -> list[Headline]:
    # Let the XML parser interpret the declaration/BOM. HTTP text decoding can
    # misread UTF-8 as Latin-1 and turn the BOM into invalid leading characters.
    xml = _get(url).content
    root = ET.fromstring(xml)
    items: list[Headline] = []
    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        if not title:
            continue
        link = (node.findtext("link") or "").strip()
        pub = node.findtext("pubDate") or node.findtext("published")
        items.append(
            Headline(
                title=title,
                source=source,
                url=link,
                published=_parse_when(pub),
            )
        )
        if len(items) >= limit:
            break
    return items


def _eurusd_ish(title: str) -> bool:
    blob = title.lower()
    keys = (
        "eur",
        "euro",
        "usd",
        "dollar",
        "fed",
        "ecb",
        "fomc",
        "cpi",
        "nfp",
        "payroll",
        "inflation",
        "forex",
        "fx ",
        "yield",
        "treasury",
        "lagarde",
        "powell",
        "warsh",
        "nagel",
        "kazaks",
        "kazaeks",
    )
    return any(k in blob for k in keys)


def fetch_headlines() -> list[Headline]:
    return harvest_eurusd_news(limit=40, deep=False)


def harvest_eurusd_news(*, limit: int = 80, deep: bool = False) -> list[Headline]:
    """Pull a wide EUR/USD headline set. ``deep`` is the 05:00 UTC / on-demand scan."""
    collected: list[Headline] = []
    rss_limit = 20 if deep else 8
    for url, source, cap in (
        (YAHOO_EURUSD, "Yahoo EURUSD", rss_limit),
        (ECB_RSS, "ECB", 6 if deep else 4),
        (FED_RSS, "Federal Reserve", 6 if deep else 4),
        (GOOGLE_EURUSD, "Google News EURUSD", 40 if deep else 12),
        (GOOGLE_POLICY, "Google News policy", 25 if deep else 8),
    ):
        try:
            collected.extend(_rss_items(url, source, limit=cap))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Headline feed {} failed: {}", source, exc)
    try:
        from src.data.newsnow import fetch_newsnow_headlines

        collected.extend(fetch_newsnow_headlines(limit=120 if deep else 24))
    except Exception as exc:  # noqa: BLE001
        logger.warning("NewsNow EUR/USD harvest failed: {}", exc)
    try:
        from src.data.forexfactory import fetch_forexfactory_headlines

        collected.extend(fetch_forexfactory_headlines(limit=80 if deep else 20))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Forex Factory EUR/USD harvest failed: {}", exc)
    relevant = [h for h in collected if _eurusd_ish(h.title)]
    rest = [h for h in collected if h not in relevant]
    seen: set[str] = set()
    out: list[Headline] = []
    for h in relevant + rest:
        key = re.sub(r"\s+", " ", h.title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
        if len(out) >= limit:
            break
    return out


def fetch_tavily_headlines(api_key: str) -> list[Headline]:
    if not api_key:
        return []
    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": "EUR/USD EURUSD today Federal Reserve ECB CPI NFP inflation dollar euro",
            "topic": "news",
            "days": 2,
            "max_results": 6,
            "search_depth": "basic",
        },
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    rows = []
    for item in payload.get("results") or []:
        rows.append(
            Headline(
                title=str(item.get("title") or "").strip(),
                source="Tavily",
                url=str(item.get("url") or ""),
            )
        )
    return [h for h in rows if h.title]


def score_sentiment(text: str) -> int:
    blob = text.lower()
    score = 0
    for phrase in BULLISH_EURUSD:
        if phrase in blob:
            score += 1
    for phrase in BEARISH_EURUSD:
        if phrase in blob:
            score -= 1
    return score


class NewsDesk:
    def __init__(self) -> None:
        self._bundle: NewsBundle | None = None
        self._as_of: datetime | None = None
        self._ttl = timedelta(minutes=20)

    def refresh(self, *, tavily_key: str = "", force: bool = False) -> NewsBundle:
        if (
            not force
            and self._bundle is not None
            and self._as_of is not None
            and utcnow() - self._as_of < self._ttl
        ):
            return self._bundle
        bundle = NewsBundle()
        try:
            bundle.events = fetch_calendar()
        except Exception as exc:  # noqa: BLE001
            bundle.errors.append(f"calendar: {exc}")
            logger.warning("EUR/USD calendar fetch failed: {}", exc)
        try:
            bundle.headlines = fetch_headlines()
        except Exception as exc:  # noqa: BLE001
            bundle.errors.append(f"headlines: {exc}")
            logger.warning("EUR/USD headlines failed: {}", exc)
        if tavily_key:
            try:
                extra = fetch_tavily_headlines(tavily_key)
                existing = {h.title.lower() for h in bundle.headlines}
                for h in extra:
                    if h.title.lower() not in existing:
                        bundle.headlines.insert(0, h)
            except Exception as exc:  # noqa: BLE001
                bundle.errors.append(f"tavily: {exc}")
                logger.warning("Tavily EUR/USD search failed: {}", exc)
        self._bundle = bundle
        self._as_of = utcnow()
        return bundle

    def events_on(self, day, *, min_impact: str = "Medium") -> list[CalendarEvent]:
        bundle = self._bundle or NewsBundle()
        rank = {"High": 3, "Medium": 2, "Low": 1, "Unknown": 0}
        need = rank.get(min_impact, 2)
        out = []
        for event in bundle.events:
            if rank.get(event.impact, 0) < need:
                continue
            if event.ts is None:
                continue
            if event.ts.astimezone(timezone.utc).date() != day:
                continue
            out.append(event)
        return out

    def blackout_reason(self, now: datetime | None = None, minutes: int = 30) -> str | None:
        now = now or utcnow()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        bundle = self._bundle or NewsBundle()
        window = timedelta(minutes=max(0, minutes))
        for event in bundle.events:
            if event.impact != "High" or event.ts is None:
                continue
            ts = event.ts if event.ts.tzinfo else event.ts.replace(tzinfo=timezone.utc)
            if abs((ts - now).total_seconds()) <= window.total_seconds():
                when = ts.strftime("%H:%M UTC")
                return (
                    f"Stand aside for high-impact {event.country} {event.title} "
                    f"at {when} (±{minutes}m news blackout)"
                )
        return None
