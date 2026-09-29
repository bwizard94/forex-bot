"""NewsNow EUR/USD headline stream.

https://www.newsnow.com/us/Business/Currencies/EUR~USD is a dated aggregator
of FXStreet, Investing.com, and other EUR/USD wires. The public HTML is
enough for the desk — no paid Essentials tier is required.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html import unescape

import requests
from loguru import logger

from src.data.news import Headline

NEWSNOW_EURUSD = "https://www.newsnow.com/us/Business/Currencies/EUR~USD"

_HL_SPLIT = re.compile(r'<div class="hl\b', flags=re.I)
_ID = re.compile(r'data-id="(\d+)"')
_LINK = re.compile(r'<a class="hll" href="([^"]+)"[^>]*>([^<]+)</a>', flags=re.I)
_PUB = re.compile(r'data-pub="([^"]+)"', flags=re.I)
_TIME = re.compile(r'data-time="(\d+)"')


def parse_newsnow_html(html: str) -> list[Headline]:
    """Pull dated headlines out of a NewsNow EUR/USD listing page."""
    items: list[Headline] = []
    seen: set[str] = set()
    for chunk in _HL_SPLIT.split(html)[1:]:
        link = _LINK.search(chunk)
        if not link:
            continue
        title = unescape(link.group(2)).strip()
        if not title or title.lower() in {"view more articles", "advertisement"}:
            continue
        key = re.sub(r"\s+", " ", title.lower())
        if key in seen:
            continue
        seen.add(key)
        href = unescape(link.group(1)).strip()
        pub = _PUB.search(chunk)
        publisher = unescape(pub.group(1)).strip() if pub else "NewsNow"
        ts = None
        time_m = _TIME.search(chunk)
        if time_m:
            try:
                ts = datetime.fromtimestamp(int(time_m.group(1)), tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                ts = None
        ext = _ID.search(chunk)
        source = f"NewsNow/{publisher}" if publisher and publisher.lower() != "newsnow" else "NewsNow"
        items.append(
            Headline(
                title=title,
                source=source,
                url=href,
                published=ts,
            )
        )
        if ext:
            items[-1].url = href or f"https://www.newsnow.com/us/Business/Currencies/EUR~USD#{ext.group(1)}"
    return items


def fetch_newsnow_headlines(limit: int = 80) -> list[Headline]:
    """HTTP GET the EUR/USD NewsNow page and return unique dated headlines."""
    try:
        response = requests.get(
            NEWSNOW_EURUSD,
            timeout=18,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ForexSentinel/2.20; EURUSD-desk)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        response.raise_for_status()
        html = response.content.decode(response.apparent_encoding or "iso-8859-1", errors="replace")
    except Exception as exc:  # noqa: BLE001
        logger.warning("NewsNow EUR/USD fetch failed: {}", exc)
        return []
    items = parse_newsnow_html(html)
    if not items:
        logger.warning("NewsNow EUR/USD page parsed 0 headlines ({} bytes)", len(html))
    return items[: max(1, limit)]
