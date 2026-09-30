"""Forex Factory news as the primary EUR/USD headline discovery source.

Public HTML is best-effort; blocked requests fall back to other news feeds.
The separate calendar feed continues to supply event context.
"""

from __future__ import annotations

import html as html_lib
import re
import copy
import time
from threading import Lock
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from loguru import logger

from src.data.news import CalendarEvent, Headline, _eurusd_ish
from src.utils import utcnow

PAGE_URL = "https://www.forexfactory.com/news"
PAIR_URL = "https://www.forexfactory.com/market/eurusd"
SOURCE = "Forex Factory EUR/USD"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 ForexSentinel/2.21"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_NEWS_URL = re.compile(
    r"(?:https?://(?:www\.)?forexfactory\.com)?/news/(\d{5,})-([a-z0-9]+(?:-[a-z0-9]+)*)",
    flags=re.I,
)
_NEWS_ANCHOR = re.compile(
    r'<a[^>]+href="[^"]*/news/(\d{5,})-([a-z0-9-]+)(?:/hit)?[^"]*"[^>]*>\s*([^<]{12,180})\s*</a>',
    flags=re.I,
)
_NEWS_MD = re.compile(
    r"\[([^\]]{12,180})\]\((https://(?:www\.)?forexfactory\.com/news/(\d{5,})-([a-z0-9-]+))\)",
    flags=re.I,
)
_LAST = re.compile(
    r"(?:EUR/USD[^.\n]{0,80}?(?:last|trades?|around|mid)|(?:last|bid|ask)(?:\s+price)?)\s*[:=]?\s*(1\.\d{4,5})",
    flags=re.I,
)

_ACRONYMS = {
    "ecb": "ECB",
    "ecbs": "ECB's",
    "fed": "Fed",
    "feds": "Fed's",
    "fomc": "FOMC",
    "usd": "USD",
    "eur": "EUR",
    "nfp": "NFP",
    "cpi": "CPI",
    "ppi": "PPI",
    "gdp": "GDP",
    "pmi": "PMI",
    "wh": "WH",
    "us": "US",
    "uk": "UK",
    "boj": "BoJ",
    "dxy": "DXY",
    "wti": "WTI",
    "ism": "ISM",
    "ifo": "IFO",
    "zew": "ZEW",
    "hicp": "HICP",
    "pce": "PCE",
    "ecb's": "ECB's",
}
_CONTRACTIONS = {
    "wont": "won't",
    "hasnt": "hasn't",
    "dont": "don't",
    "isnt": "isn't",
    "didnt": "didn't",
    "cant": "can't",
}
_SMALL = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "from",
    "with",
    "but",
    "if",
    "our",
    "into",
    "as",
    "at",
    "by",
}


def _to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "")
    if not text or text in {"n/a", "NA", "—", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _is_challenge(html: str) -> bool:
    blob = (html or "").lower()
    return any(
        token in blob
        for token in (
            "just a moment",
            "cf-chl",
            "challenge-platform",
            "enable javascript and cookies to continue",
        )
    )


def slug_to_title(slug: str) -> str:
    """Turn a Forex Factory news slug into a readable headline."""
    parts = [p for p in (slug or "").replace("_", "-").strip("-").split("-") if p]
    out: list[str] = []
    for i, part in enumerate(parts):
        low = part.lower()
        if low in _ACRONYMS:
            out.append(_ACRONYMS[low])
            continue
        if low in _CONTRACTIONS:
            word = _CONTRACTIONS[low]
            out.append(word[:1].upper() + word[1:] if i == 0 else word)
            continue
        if i > 0 and low in _SMALL:
            out.append(low)
            continue
        out.append(low[:1].upper() + low[1:])
    return " ".join(out)


def _canonical_url(news_id: str, slug: str) -> str:
    clean = slug.split("/", 1)[0].split("#", 1)[0].strip("-")
    return f"https://www.forexfactory.com/news/{news_id}-{clean}"


def parse_news_links(blob: str) -> list[Headline]:
    """Pull unique Forex Factory news items from HTML, markdown, or a URL dump."""
    text = blob or ""
    titles: dict[str, str] = {}
    slugs: dict[str, str] = {}

    for match in _NEWS_ANCHOR.finditer(text):
        news_id, slug, title = match.group(1), match.group(2), html_lib.unescape(match.group(3)).strip()
        if title.lower() in {"hit", "view", "comments", "read more"}:
            continue
        titles[news_id] = title
        slugs[news_id] = slug

    for match in _NEWS_MD.finditer(text):
        title, _url, news_id, slug = match.group(1), match.group(2), match.group(3), match.group(4)
        titles.setdefault(news_id, html_lib.unescape(title).strip())
        slugs.setdefault(news_id, slug)

    for match in _NEWS_URL.finditer(text):
        news_id, slug = match.group(1), match.group(2)
        if slug.lower() in {"hit", "post"}:
            continue
        slugs.setdefault(news_id, slug)

    items: list[Headline] = []
    seen: set[str] = set()
    for news_id, slug in slugs.items():
        title = titles.get(news_id) or slug_to_title(slug)
        key = re.sub(r"\s+", " ", title.lower())
        if not title or key in seen:
            continue
        seen.add(key)
        items.append(
            Headline(
                title=title,
                source=SOURCE,
                url=_canonical_url(news_id, slug),
            )
        )
    return items


@dataclass
class FFSnapshot:
    last: float | None = None
    news: list[Headline] = field(default_factory=list)
    events: list[CalendarEvent] = field(default_factory=list)
    url: str = PAGE_URL
    fetched_at: datetime | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "last": self.last,
            "news": [item.as_dict() for item in self.news],
            "events": [item.as_dict() for item in self.events],
            "url": self.url,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "errors": list(self.errors),
            "source": SOURCE,
        }

    def next_high(self) -> CalendarEvent | None:
        now = self.fetched_at or utcnow()
        ranked: list[CalendarEvent] = []
        for event in self.events:
            if event.impact != "High" or event.ts is None:
                continue
            ts = event.ts if event.ts.tzinfo else event.ts.replace(tzinfo=timezone.utc)
            if ts < now - timedelta(minutes=5):
                continue
            ranked.append(event)
        ranked.sort(key=lambda e: e.ts or datetime.max.replace(tzinfo=timezone.utc))
        return ranked[0] if ranked else None

    def driver_lines(self) -> list[str]:
        lines: list[str] = [
            f"Forex Factory [news]({PAGE_URL}) is the primary pair news reference — context, not a ticket."
        ]
        if self.last is not None:
            lines.append(f"Forex Factory last `{self.last:.4f}` (context only; OANDA is the fill).")
        nxt = self.next_high()
        if nxt is not None and nxt.ts is not None:
            ts = nxt.ts if nxt.ts.tzinfo else nxt.ts.replace(tzinfo=timezone.utc)
            lines.append(
                f"Forex Factory next red print: {nxt.country} {nxt.title} at "
                f"{ts.strftime('%H:%M UTC')} — stand aside ±30 minutes."
            )
        elif self.events:
            upcoming = [e for e in self.events if e.impact in {"High", "Medium"}][:2]
            if upcoming:
                bits = ", ".join(f"{e.country} {e.title}" for e in upcoming)
                lines.append(f"Forex Factory calendar still in the book: {bits}.")
        for item in self.news[:3]:
            lines.append(f"Forex Factory news: {item.title}")
        if self.errors and not self.news:
            lines.append("Forex Factory market page was blocked or empty this cycle. Calendar JSON still feeds the blackout.")
        return lines[:8]


def parse_snapshot(html: str, *, now: datetime | None = None, url: str = PAGE_URL) -> FFSnapshot:
    """Read relevant news; quote extraction is restricted to the pair page."""
    snap = FFSnapshot(url=url, fetched_at=now or utcnow())
    if _is_challenge(html):
        snap.errors.append("Forex Factory returned a Cloudflare challenge. Live fetch skipped this cycle.")
        return snap
    if not html or len(html) < 80:
        snap.errors.append("Forex Factory page was empty.")
        return snap

    snap.news = [item for item in parse_news_links(html) if _eurusd_ish(item.title)]
    last = _LAST.search(html) if url == PAIR_URL else None
    if last:
        snap.last = _to_float(last.group(1))
    if not snap.news and snap.last is None:
        snap.errors.append("Could not read Forex Factory EUR/USD news or last.")
    return snap


def fetch_page(timeout: float = 20.0) -> str:
    response = requests.get(PAGE_URL, headers=_UA, timeout=timeout)
    if response.status_code in {202, 403, 429, 503}:
        raise RuntimeError(f"Forex Factory blocked ({response.status_code})")
    response.raise_for_status()
    return response.text


_FETCH_LOCK = Lock()
_NEWS_CACHE: FFSnapshot | None = None
_RETRY_AFTER = 0.0
_SOURCE_STATUS: dict[str, Any] = {"state": "pending", "url": PAGE_URL, "checked_at": None}
FETCH_INTERVAL_SECONDS = 300


def source_status() -> dict[str, Any]:
    """Non-blocking diagnostics; availability is not publication freshness."""
    status = dict(_SOURCE_STATUS)
    checked = status.get("checked_at")
    if checked and (utcnow() - datetime.fromisoformat(checked)).total_seconds() > 2400:
        status["state"] = "stale"
    return status


def _fetch_news_snapshot(*, timeout: float = 20.0) -> FFSnapshot:
    global _NEWS_CACHE, _RETRY_AFTER, _SOURCE_STATUS
    with _FETCH_LOCK:
        if _NEWS_CACHE is not None and time.monotonic() < _RETRY_AFTER:
            return copy.deepcopy(_NEWS_CACHE)
        now = utcnow()
        try:
            snap = parse_snapshot(fetch_page(timeout=timeout), now=now)
            state = "available" if snap.news else "unavailable"
            if any("challenge" in error.lower() for error in snap.errors):
                state = "blocked"
        except Exception as exc:  # noqa: BLE001
            # Do not expose request URLs, proxy details or credentials in diagnostics.
            state = "blocked" if "blocked" in str(exc).lower() else "unavailable"
            snap = FFSnapshot(fetched_at=now, errors=[
                f"Forex Factory fetch failed ({state}); other headline feeds remain available."
            ])
        finished = utcnow()
        _SOURCE_STATUS = {
            "state": state, "url": PAGE_URL, "checked_at": now.isoformat(),
            "retry_after": (finished + timedelta(seconds=FETCH_INTERVAL_SECONDS)).isoformat(),
            "headline_count": len(snap.news), "errors": list(snap.errors),
            "publication_time_verified": False,
        }
        _NEWS_CACHE = copy.deepcopy(snap)
        _RETRY_AFTER = time.monotonic() + FETCH_INTERVAL_SECONDS
        if snap.errors:
            logger.warning("Forex Factory news: {}", "; ".join(snap.errors))
        return snap


def fetch_forexfactory_headlines(limit: int = 40) -> list[Headline]:
    """Read relevant primary headlines, sharing a bounded cache with intel."""
    if limit <= 0:
        return []
    return _fetch_news_snapshot().news[:limit]


def fetch_eurusd_snapshot(*, timeout: float = 20.0, now: datetime | None = None) -> FFSnapshot:
    now = now or utcnow()
    snap = _fetch_news_snapshot(timeout=timeout)
    try:
        from src.data.news import fetch_calendar

        events = fetch_calendar()
        horizon = now + timedelta(hours=48)
        kept: list[CalendarEvent] = []
        for event in events:
            if event.ts is None:
                continue
            ts = event.ts if event.ts.tzinfo else event.ts.replace(tzinfo=timezone.utc)
            if ts < now - timedelta(hours=6) or ts > horizon:
                continue
            if event.impact not in {"High", "Medium"}:
                continue
            kept.append(event)
            if len(kept) >= 8:
                break
        snap.events = kept
    except Exception as exc:  # noqa: BLE001
        logger.warning("Forex Factory calendar attach failed: {}", exc)
        snap.errors.append(f"calendar: {exc}")
    return snap
