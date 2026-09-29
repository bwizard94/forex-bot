"""Trading Economics euro-area currency page as an EUR/USD intel source.

Public page: https://tradingeconomics.com/euro-area/currency

The desk reads the EUR/USD last, day/month/year change, TE model forecasts,
related Euro Area / US inflation and policy rates, EUR crosses, and the
site's euro news stream. That snapshot feeds price integrity, the living
playbook, and Slack #forex. It is context — not an order book.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import requests
from loguru import logger

from src.utils import utcnow

PAGE_URL = "https://tradingeconomics.com/euro-area/currency"
SOURCE = "Trading Economics EUR/USD"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 ForexSentinel/2.7"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

RELATED_NOTES: tuple[tuple[str, str, str], ...] = (
    (
        "/euro-area/inflation-cpi",
        "EA CPI",
        "Rising Eurozone inflation can support EUR via ECB hikes; a cool print weighs on EUR/USD.",
    ),
    (
        "/united-states/inflation-cpi",
        "US CPI",
        "Hotter US inflation typically bids USD and presses EUR/USD.",
    ),
    (
        "/united-states/interest-rate",
        "Fed funds",
        "A higher Fed funds rate usually bids USD. The Fed–ECB gap is a core EUR/USD driver.",
    ),
    (
        "/euro-area/interest-rate",
        "ECB rate",
        "A higher ECB deposit/refi rate supports EUR; a cut or dovish hold weighs on EUR/USD.",
    ),
    (
        "/united-states/non-farm-payrolls",
        "US NFP",
        "A strong payrolls beat typically bids USD; a miss can lift EUR/USD.",
    ),
    (
        "/united-states/unemployment-rate",
        "US jobless",
        "Rising US unemployment can soften USD and lift EUR/USD; a drop does the opposite.",
    ),
    (
        "/euro-area/unemployment-rate",
        "EA jobless",
        "A jump in Eurozone unemployment weighs on EUR; a drop can support EUR/USD.",
    ),
)

CROSS_PRIORITY = ("EURUSD", "EURGBP", "EURJPY", "EURCHF", "EURCNY")


def _to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "").replace("%", "").replace("\\", "")
    if not text or text in {"n/a", "NA", "—", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pct(raw: str | None) -> float | None:
    return _to_float(raw)


def _strip_tags(blob: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", blob)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _span_id(html: str, element_id: str) -> str | None:
    match = re.search(
        rf'id=["\']{re.escape(element_id)}["\'][^>]*>(.*?)</(?:span|td|div)>',
        html,
        flags=re.I | re.S,
    )
    if not match:
        return None
    text = _strip_tags(match.group(1))
    return text or None


def _header_value(html: str, label: str) -> str | None:
    match = re.search(
        rf">\s*{re.escape(label)}\s*</div>(.*?)</div>",
        html,
        flags=re.I | re.S,
    )
    if not match:
        return None
    chunk = match.group(1)
    pcts = re.findall(r"([+-]?\d+(?:\.\d+)?\s*%)", chunk)
    if pcts:
        return pcts[0].strip()
    nums = re.findall(r"([+-]?\d+(?:\.\d+)?)", _strip_tags(chunk))
    return nums[-1] if nums else None


def _js_assign(html: str, name: str) -> str | None:
    matches = re.findall(rf"{re.escape(name)}\s*=\s*([^;]+);", html)
    nonempty = [item.strip() for item in matches if item.strip() not in {"", "[]", "''", '""'}]
    if nonempty:
        return nonempty[-1]
    return matches[-1].strip() if matches else None


@dataclass(slots=True)
class TERelated:
    name: str
    last: float | None
    previous: float | None
    unit: str
    reference: str
    note: str
    path: str = ""
    key: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TECross:
    symbol: str
    last: float | None
    day_pct: float | None
    year_pct: float | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TENews:
    title: str
    url: str
    published: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TESnapshot:
    last: float | None = None
    daily_change: float | None = None
    daily_pct: float | None = None
    monthly_pct: float | None = None
    yearly_pct: float | None = None
    quarter_forecast: float | None = None
    year_forecast: float | None = None
    forecasts: list[float] = field(default_factory=list)
    summary: str = ""
    stats: str = ""
    forecast_text: str = ""
    related: list[TERelated] = field(default_factory=list)
    crosses: list[TECross] = field(default_factory=list)
    news: list[TENews] = field(default_factory=list)
    url: str = PAGE_URL
    fetched_at: datetime | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "last": self.last,
            "daily_change": self.daily_change,
            "daily_pct": self.daily_pct,
            "monthly_pct": self.monthly_pct,
            "yearly_pct": self.yearly_pct,
            "quarter_forecast": self.quarter_forecast,
            "year_forecast": self.year_forecast,
            "forecasts": list(self.forecasts),
            "summary": self.summary,
            "stats": self.stats,
            "forecast_text": self.forecast_text,
            "related": [item.as_dict() for item in self.related],
            "crosses": [item.as_dict() for item in self.crosses],
            "news": [item.as_dict() for item in self.news],
            "url": self.url,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "errors": list(self.errors),
            "source": SOURCE,
        }

    def related_named(self, name: str) -> TERelated | None:
        needle = name.lower()
        return next(
            (
                item
                for item in self.related
                if needle in item.name.lower() or needle == item.key.lower() or needle in item.key.lower()
            ),
            None,
        )

    def policy_spread_note(self) -> str | None:
        fed = self.related_named("Fed funds")
        ecb = self.related_named("ECB rate")
        if fed is None or ecb is None or fed.last is None or ecb.last is None:
            return None
        gap = fed.last - ecb.last
        direction = "USD still pays more than EUR" if gap > 0 else "EUR policy rate is above Fed funds"
        return (
            f"Policy spread: Fed funds {fed.last:.2f}% vs ECB {ecb.last:.2f}% "
            f"({gap:+.2f} pp). {direction} — a wide USD yield advantage usually weighs on EUR/USD."
        )

    def driver_lines(self) -> list[str]:
        lines: list[str] = []
        if self.last is not None:
            bits = [f"Trading Economics EUR/USD last `{self.last:.5f}`"]
            if self.daily_pct is not None:
                bits.append(f"day {self.daily_pct:+.2f}%")
            if self.monthly_pct is not None:
                bits.append(f"month {self.monthly_pct:+.2f}%")
            if self.yearly_pct is not None:
                bits.append(f"year {self.yearly_pct:+.2f}%")
            lines.append(", ".join(bits) + f" ({PAGE_URL}).")
        if self.yearly_pct is not None and self.yearly_pct <= -1:
            lines.append(
                "TE yearly print is still a weaker euro. Do not buy a recovery forecast against a live H1 downtrend."
            )
        elif self.yearly_pct is not None and self.yearly_pct >= 1:
            lines.append("TE yearly print is a firmer euro. Fade longs only at a stretched extreme.")
        if self.quarter_forecast is not None or self.year_forecast is not None:
            q = f"{self.quarter_forecast:.2f}" if self.quarter_forecast is not None else "n/a"
            y = f"{self.year_forecast:.2f}" if self.year_forecast is not None else "n/a"
            lines.append(
                f"TE models EUR/USD at {q} by quarter-end and {y} in 12 months. "
                "That is a slow mean-reversion map, not a ticket to fade H1."
            )
        spread = self.policy_spread_note()
        if spread:
            lines.append(spread)
        for item in self.related:
            if item.last is None:
                continue
            prev = f" (prev {item.previous:g})" if item.previous is not None else ""
            ref = f" {item.reference}" if item.reference else ""
            unit = f" {item.unit}" if item.unit else ""
            lines.append(f"TE {item.name}: {item.last:g}{unit}{prev}{ref}. {item.note}")
        if self.summary:
            lines.append(self.summary[:320])
        return lines[:8]


def parse_snapshot(html: str, *, now: datetime | None = None, url: str = PAGE_URL) -> TESnapshot:
    """Pull EUR/USD last, changes, forecasts, related rates, crosses, and news from the page HTML."""
    snap = TESnapshot(url=url, fetched_at=now or utcnow())
    if not html or len(html) < 200:
        snap.errors.append("Trading Economics page was empty.")
        return snap

    last = _to_float(_span_id(html, "market_last"))
    if last is None:
        meta = re.search(r'TEChartsMeta\s*=\s*(\[.*?\]);', html, flags=re.S)
        if meta:
            value = re.search(r'"value"\s*:\s*([0-9.]+)', meta.group(1))
            last = _to_float(value.group(1) if value else None)
    if last is None:
        desc = re.search(
            r'EUR/USD exchange rate (?:rose|fell|was) to ([0-9.]+)',
            html,
            flags=re.I,
        )
        last = _to_float(desc.group(1) if desc else None)
    snap.last = last
    snap.daily_change = _to_float(_span_id(html, "market_daily_chg"))
    snap.daily_pct = _pct(_span_id(html, "market_daily_Pchg"))
    if snap.daily_pct is None:
        snap.daily_pct = _pct(_header_value(html, "Daily Change"))
    snap.monthly_pct = _pct(_header_value(html, "Monthly"))
    snap.yearly_pct = _pct(_header_value(html, "Yearly"))
    q_label = re.search(r"(Q[1-4]\s+Forecast)", html, flags=re.I)
    if q_label:
        snap.quarter_forecast = _to_float(_header_value(html, q_label.group(1)))
    if snap.quarter_forecast is None:
        snap.quarter_forecast = _to_float(_header_value(html, "Q3 Forecast")) or _to_float(
            _header_value(html, "Q4 Forecast")
        )

    raw_forecast = _js_assign(html, "TEForecast")
    if raw_forecast:
        snap.forecasts = [_to_float(part) for part in re.findall(r"[0-9]+\.[0-9]+", raw_forecast)]
        snap.forecasts = [value for value in snap.forecasts if value is not None]
        if snap.quarter_forecast is None and snap.forecasts:
            snap.quarter_forecast = snap.forecasts[0]
        if snap.forecasts:
            snap.year_forecast = snap.forecasts[-1]

    desc = re.search(r'<h2[^>]*id="description"[^>]*>(.*?)</h2>', html, flags=re.I | re.S)
    if desc:
        snap.summary = _strip_tags(desc.group(1))
    stats = re.search(
        r"Euro US Dollar Exchange Rate - EUR/USD - Stats.*?<h2[^>]*>(.*?)</h2>",
        html,
        flags=re.I | re.S,
    )
    if stats:
        snap.stats = _strip_tags(stats.group(1))
    forecast_body = re.search(
        r"Euro US Dollar Exchange Rate - EUR/USD - Forecast.*?<h3[^>]*>(.*?)</h3>",
        html,
        flags=re.I | re.S,
    )
    if forecast_body:
        snap.forecast_text = _strip_tags(forecast_body.group(1))
        if snap.year_forecast is None:
            year = re.search(r"trade at ([0-9.]+) in 12 months", snap.forecast_text, flags=re.I)
            snap.year_forecast = _to_float(year.group(1) if year else None)
        if snap.quarter_forecast is None:
            quarter = re.search(r"trade at ([0-9.]+) by the end of this quarter", snap.forecast_text, flags=re.I)
            snap.quarter_forecast = _to_float(quarter.group(1) if quarter else None)

    snap.related = _parse_related(html)
    snap.crosses = _parse_crosses(html)
    snap.news = _parse_news(html)
    if snap.last is None:
        snap.errors.append("Could not read a Trading Economics EUR/USD last.")
    return snap


def _parse_related(html: str) -> list[TERelated]:
    out: list[TERelated] = []
    lower = html.lower()
    for path, name, note in RELATED_NOTES:
        idx = lower.find(path.lower())
        if idx < 0:
            continue
        chunk = html[idx : idx + 1200]
        nums = [_to_float(v) for v in re.findall(r">\s*([+-]?\d+(?:\.\d+)?)\s*<", chunk)]
        nums = [v for v in nums if v is not None]
        unit_match = re.search(r">\s*(percent|Thousand|Index Points|USD Billion)\s*<", chunk, flags=re.I)
        ref_match = re.search(r">\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\s*<", chunk, flags=re.I)
        title_match = re.search(r">([^<]{8,80})</a>", chunk)
        out.append(
            TERelated(
                name=(title_match.group(1).strip() if title_match else name),
                last=nums[0] if nums else None,
                previous=nums[1] if len(nums) > 1 else None,
                unit=(unit_match.group(1) if unit_match else "percent"),
                reference=(ref_match.group(1) if ref_match else ""),
                note=note,
                path=path,
                key=name,
            )
        )
    return out


def _parse_crosses(html: str) -> list[TECross]:
    found: dict[str, TECross] = {}
    for match in re.finditer(
        r'data-symbol="(EUR[A-Z]{3}):CUR".*?<td id="p">\s*([\d.,]+)\s*</td>'
        r'.*?<td[^>]*id="pch"[^>]*>\s*([+-]?\d+(?:\.\d+)?%|0%)'
        r".*?</tr>",
        html,
        flags=re.I | re.S,
    ):
        symbol = match.group(1).upper()
        year_cell = re.findall(r">\s*([+-]?\d+(?:\.\d+)?%)\s*<", match.group(0))
        year_pct = _pct(year_cell[-1] if len(year_cell) >= 2 else None)
        found[symbol] = TECross(
            symbol=symbol,
            last=_to_float(match.group(2)),
            day_pct=_pct(match.group(3)),
            year_pct=year_pct,
        )
    ordered = [found[sym] for sym in CROSS_PRIORITY if sym in found]
    extras = [item for key, item in found.items() if key not in CROSS_PRIORITY]
    return (ordered + extras)[:12]


def _parse_news(html: str) -> list[TENews]:
    out: list[TENews] = []
    seen: set[str] = set()
    for match in re.finditer(
        r"""href=(["'])((?:https://tradingeconomics.com)?/euro-area/currency/news/\d+)\1\s*>"""
        r"(?:<[^>]+>)*([^<]{16,200})",
        html,
        flags=re.I,
    ):
        title = html_lib.unescape(match.group(3)).strip()
        if title.lower() in seen:
            continue
        seen.add(title.lower())
        href = match.group(2)
        url = href if href.startswith("http") else "https://tradingeconomics.com" + href
        published = ""
        after = html[match.end() : match.end() + 400]
        date = re.search(r"(20\d{2}-\d{2}-\d{2})", after)
        if date:
            published = date.group(1)
        out.append(TENews(title=title, url=url, published=published))
        if len(out) >= 5:
            break
    return out


def fetch_page(timeout: float = 20.0) -> str:
    response = requests.get(PAGE_URL, headers=_UA, timeout=timeout)
    response.raise_for_status()
    return response.text


def fetch_eurusd_snapshot(*, timeout: float = 20.0, now: datetime | None = None) -> TESnapshot:
    try:
        html = fetch_page(timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Trading Economics euro-area currency fetch failed: {}", exc)
        return TESnapshot(fetched_at=now or utcnow(), errors=[f"Trading Economics fetch failed: {exc}"])
    try:
        return parse_snapshot(html, now=now)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Trading Economics euro-area currency parse failed: {}", exc)
        return TESnapshot(fetched_at=now or utcnow(), errors=[f"Trading Economics parse failed: {exc}"])
