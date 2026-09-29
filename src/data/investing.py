"""Investing.com EUR/USD quote page as an intel source.

Public page: https://www.investing.com/currencies/eur-usd

The desk reads the pair last, bid/ask, day and 52-week range, the
multi-timeframe technical summary (30m through monthly), CME euro
futures, the pair-page economic calendar (claims, CPI, CFTC EUR), and
the euro/dollar news stream. That snapshot feeds price integrity and
the living playbook. It is context — not an order book. Direct HTTP
often hits Cloudflare 403; parse still works on saved HTML/markdown,
and a blocked fetch never stops the intel cycle.
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

PAGE_URL = "https://www.investing.com/currencies/eur-usd"
SOURCE = "Investing.com EUR/USD"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 ForexSentinel/2.10"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

TA_LABELS = (
    ("30m", r"30\s*Min"),
    ("hourly", r"Hourly"),
    ("5h", r"5\s*Hours"),
    ("daily", r"Daily"),
    ("weekly", r"Weekly"),
    ("monthly", r"Monthly"),
)
TA_SCORE = r"(Strong\s*Sell|Strong\s*Buy|Neutral|Sell|Buy)"


def _to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "").replace("%", "").replace("$", "").rstrip(".")
    text = text.replace("\\", "").replace("−", "-")
    if not text or text in {"n/a", "NA", "N/A", "—", "-", "–"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _plain(blob: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", blob)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = text.replace("\\-", "-").replace("\\+", "+").replace("−", "-")
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_challenge(html: str) -> bool:
    blob = (html or "").lower()
    return any(
        token in blob
        for token in (
            "just a moment",
            "cf-chl",
            "challenge-platform",
            "enable javascript and cookies to continue",
            "attention required",
            "access denied",
        )
    )


def _norm_ta(raw: str | None) -> str:
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw).strip().title().replace("Sell", "Sell").replace("Buy", "Buy")


@dataclass(slots=True)
class INVNews:
    title: str
    url: str = ""
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class INVCal:
    name: str
    actual: float | None
    forecast: float | None
    previous: float | None
    unit: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class INVSnapshot:
    last: float | None = None
    change: float | None = None
    daily_pct: float | None = None
    bid: float | None = None
    ask: float | None = None
    day_low: float | None = None
    day_high: float | None = None
    open: float | None = None
    prev_close: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    year_pct: float | None = None
    summary: str = ""
    ta_30m: str = ""
    ta_hourly: str = ""
    ta_5h: str = ""
    ta_daily: str = ""
    ta_weekly: str = ""
    ta_monthly: str = ""
    cme_last: float | None = None
    cftc_eur_k: float | None = None
    claims_k: float | None = None
    claims_cons_k: float | None = None
    housing_m: float | None = None
    ea_cpi: float | None = None
    ea_core: float | None = None
    philly: float | None = None
    dxy: float | None = None
    wti: float | None = None
    gold: float | None = None
    vix: float | None = None
    calendar: list[INVCal] = field(default_factory=list)
    news: list[INVNews] = field(default_factory=list)
    url: str = PAGE_URL
    fetched_at: datetime | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "last": self.last,
            "change": self.change,
            "daily_pct": self.daily_pct,
            "bid": self.bid,
            "ask": self.ask,
            "day_low": self.day_low,
            "day_high": self.day_high,
            "open": self.open,
            "prev_close": self.prev_close,
            "high_52w": self.high_52w,
            "low_52w": self.low_52w,
            "year_pct": self.year_pct,
            "summary": self.summary,
            "ta_30m": self.ta_30m,
            "ta_hourly": self.ta_hourly,
            "ta_5h": self.ta_5h,
            "ta_daily": self.ta_daily,
            "ta_weekly": self.ta_weekly,
            "ta_monthly": self.ta_monthly,
            "cme_last": self.cme_last,
            "cftc_eur_k": self.cftc_eur_k,
            "claims_k": self.claims_k,
            "claims_cons_k": self.claims_cons_k,
            "housing_m": self.housing_m,
            "ea_cpi": self.ea_cpi,
            "ea_core": self.ea_core,
            "philly": self.philly,
            "dxy": self.dxy,
            "wti": self.wti,
            "gold": self.gold,
            "vix": self.vix,
            "calendar": [item.as_dict() for item in self.calendar],
            "news": [item.as_dict() for item in self.news],
            "url": self.url,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "errors": list(self.errors),
            "source": SOURCE,
        }

    def stacked_sell(self) -> bool:
        daily = (self.ta_daily or self.summary).lower()
        weekly = (self.ta_weekly or "").lower()
        return "sell" in daily and "sell" in weekly

    def driver_lines(self) -> list[str]:
        lines: list[str] = []
        if self.last is not None:
            chg = f", day {self.daily_pct:+.2f}%" if self.daily_pct is not None else ""
            rng = ""
            if self.day_low is not None and self.day_high is not None:
                rng = f"  range `{self.day_low:.4f}`–`{self.day_high:.4f}`"
            lines.append(f"Investing.com EUR/USD last `{self.last:.4f}`{chg}{rng} ({PAGE_URL}).")
        if self.summary or self.ta_daily:
            bits = [self.summary or self.ta_daily]
            if self.ta_hourly:
                bits.append(f"H1 {self.ta_hourly}")
            if self.ta_weekly:
                bits.append(f"W {self.ta_weekly}")
            if self.ta_monthly:
                bits.append(f"M {self.ta_monthly}")
            lines.append(
                "Investing.com technicals: "
                + ", ".join(bits)
                + ". Multi-TF Strong Sell is not a license to short the day low."
            )
        if self.cme_last is not None:
            lines.append(
                f"Investing.com CME euro futures `{self.cme_last:.4f}` — sits at Barchart R1. "
                "Fade rips into that zone; do not buy the break of the day's high."
            )
        if self.cftc_eur_k is not None and self.cftc_eur_k < 0:
            lines.append(
                f"Investing.com CFTC EUR specs `{self.cftc_eur_k:.1f}k` net (prev). "
                "Crowded short — do not pile in at the washout."
            )
        cal_bits = []
        if self.claims_k is not None:
            vs = f" vs {self.claims_cons_k:.0f}k cons" if self.claims_cons_k is not None else ""
            cal_bits.append(f"claims `{self.claims_k:.0f}k`{vs}")
        if self.ea_cpi is not None:
            core = f", core {self.ea_core:.1f}%" if self.ea_core is not None else ""
            cal_bits.append(f"EA CPI {self.ea_cpi:.1f}%{core}")
        if self.housing_m is not None:
            cal_bits.append(f"housing starts `{self.housing_m:.3f}M`")
        if cal_bits:
            lines.append("Investing.com calendar: " + ", ".join(cal_bits) + ". A claims beat typically bids USD.")
        if self.year_pct is not None:
            lines.append(
                f"Investing.com 1-year change `{self.year_pct:+.2f}%`. "
                "That agrees with TE's weaker-euro yearly print — do not buy a 1.16 recovery against live H1."
            )
        related = []
        if self.dxy is not None:
            related.append(f"DXY `{self.dxy:.2f}`")
        if self.wti is not None:
            related.append(f"WTI `${self.wti:.2f}`")
        if self.gold is not None:
            related.append(f"gold `{self.gold:.0f}`")
        if related:
            lines.append("Investing.com tape: " + ", ".join(related) + ".")
        if self.news:
            lines.append(f"Investing.com: {self.news[0].title}")
        return lines[:8]


def parse_snapshot(html: str, *, now: datetime | None = None, url: str = PAGE_URL) -> INVSnapshot:
    """Pull last, TA summary, calendar, CME, and news from the EUR/USD page."""
    snap = INVSnapshot(url=url, fetched_at=now or utcnow())
    if _is_challenge(html):
        snap.errors.append("Investing.com returned a Cloudflare challenge. Live fetch skipped this cycle.")
        return snap
    if not html or len(html) < 200:
        snap.errors.append("Investing.com page was empty.")
        return snap

    text = _plain(html)
    _parse_quote(snap, text)
    _parse_ta(snap, text)
    _parse_calendar(snap, text)
    _parse_related(snap, text)
    _parse_news(snap, html)
    if snap.last is None:
        snap.errors.append("Could not read an Investing.com EUR/USD last.")
    return snap


def _parse_quote(snap: INVSnapshot, text: str) -> None:
    faq = re.search(r"current EUR/USD exchange rate is\s+(1\.\d{3,5})", text, flags=re.I)
    if faq:
        snap.last = _to_float(faq.group(1))
    header = re.search(
        r"Add to Watchlist\s+(1\.\d{3,5})\s+([+-][\d.]+)\s*\(([+-]?[\d.]+)%\)",
        text,
        flags=re.I,
    )
    if header:
        snap.last = snap.last or _to_float(header.group(1))
        snap.change = _to_float(header.group(2))
        snap.daily_pct = _to_float(header.group(3))
    if snap.last is None:
        live = re.search(r"Real-time Currencies.{0,80}?(1\.\d{4})\s+([+-][\d.]+)%", text, flags=re.I | re.S)
        if live:
            snap.last = _to_float(live.group(1))
            snap.daily_pct = _to_float(live.group(2))

    rng = re.search(
        r"(?:Today.s EUR/USD range is from|Day.s Range)\s+(1\.\d{3,5})\s*(?:to|\-)\s*(1\.\d{3,5})",
        text,
        flags=re.I,
    )
    if rng:
        snap.day_low = _to_float(rng.group(1))
        snap.day_high = _to_float(rng.group(2))
    wk = re.search(
        r"52-week range for EUR/USD is\s+(1\.\d{3,5})\s+to\s+(1\.\d{3,5})",
        text,
        flags=re.I,
    )
    if not wk:
        wk = re.search(r"52 wk Range\s+(1\.\d{3,5})\s+(1\.\d{3,5})", text, flags=re.I)
    if wk:
        snap.low_52w = _to_float(wk.group(1))
        snap.high_52w = _to_float(wk.group(2))
    bid = re.search(r"bid price is\s+(1\.\d{3,5})", text, flags=re.I)
    ask = re.search(r"ask price is\s+(1\.\d{3,5})", text, flags=re.I)
    snap.bid = _to_float(bid.group(1) if bid else None)
    snap.ask = _to_float(ask.group(1) if ask else None)
    if snap.bid is None:
        ba = re.search(r"\bBid\s+(1\.\d{3,5})\s+Ask\s+(1\.\d{3,5})", text, flags=re.I)
        if ba:
            snap.bid = _to_float(ba.group(1))
            snap.ask = _to_float(ba.group(2))
    prev = re.search(
        r"(?:previous close of|Prev\. Close)\s+(1\.\d{3,5})",
        text,
        flags=re.I,
    )
    snap.prev_close = _to_float(prev.group(1) if prev else None)
    opened = re.search(
        r"(?:opening price for EUR/USD today was|Open)\s+(1\.\d{3,5})",
        text,
        flags=re.I,
    )
    snap.open = _to_float(opened.group(1) if opened else None)
    year = re.search(r"1-Year Change\s+([+-]?[\d.]+)\s*%", text, flags=re.I)
    snap.year_pct = _to_float(year.group(1) if year else None)
    cme = re.search(r"\bCME\b.{0,80}?(1\.\d{4})", text, flags=re.I | re.S)
    if cme:
        snap.cme_last = _to_float(cme.group(1))


def _parse_ta(snap: INVSnapshot, text: str) -> None:
    rated = re.search(r"currently rated\s+(Strong\s+Sell|Strong\s+Buy|Sell|Buy|Neutral)", text, flags=re.I)
    if rated:
        snap.summary = _norm_ta(rated.group(1))
    jammed = re.search(
        rf"30\s*Min\s*{TA_SCORE}\s*Hourly\s*{TA_SCORE}\s*5\s*Hours\s*{TA_SCORE}"
        rf"\s*Daily\s*{TA_SCORE}\s*Weekly\s*{TA_SCORE}\s*Monthly\s*{TA_SCORE}",
        text,
        flags=re.I,
    )
    if jammed:
        snap.ta_30m = _norm_ta(jammed.group(1))
        snap.ta_hourly = _norm_ta(jammed.group(2))
        snap.ta_5h = _norm_ta(jammed.group(3))
        snap.ta_daily = _norm_ta(jammed.group(4))
        snap.ta_weekly = _norm_ta(jammed.group(5))
        snap.ta_monthly = _norm_ta(jammed.group(6))
        snap.summary = snap.summary or snap.ta_daily
        return
    mapping = {
        "30m": "ta_30m",
        "hourly": "ta_hourly",
        "5h": "ta_5h",
        "daily": "ta_daily",
        "weekly": "ta_weekly",
        "monthly": "ta_monthly",
    }
    for key, pattern in TA_LABELS:
        match = re.search(rf"{pattern}\s*{TA_SCORE}", text, flags=re.I)
        if match:
            setattr(snap, mapping[key], _norm_ta(match.group(1)))
    snap.summary = snap.summary or snap.ta_daily


def _parse_calendar(snap: INVSnapshot, text: str) -> None:
    claims = re.search(
        r"Initial Jobless Claims.{0,220}?Act:\s*([\d.,]+)\s*K.{0,80}?Cons:\s*([\d.,]+)\s*K",
        text,
        flags=re.I | re.S,
    )
    if claims:
        snap.claims_k = _to_float(claims.group(1))
        snap.claims_cons_k = _to_float(claims.group(2))
        snap.calendar.append(
            INVCal(name="Initial Jobless Claims", actual=snap.claims_k, forecast=snap.claims_cons_k, previous=None, unit="k")
        )
    housing = re.search(
        r"Housing Starts \(Aug\).{0,220}?Act:\s*([\d.]+)\s*M.{0,80}?Cons:\s*([\d.]+)\s*M",
        text,
        flags=re.I | re.S,
    )
    if housing:
        snap.housing_m = _to_float(housing.group(1))
        snap.calendar.append(
            INVCal(
                name="Housing Starts",
                actual=snap.housing_m,
                forecast=_to_float(housing.group(2)),
                previous=None,
                unit="M",
            )
        )
    cpi = re.search(
        r"\[CPI \(YoY\) \(Aug\)\].{0,220}?Act:\s*([\d.]+)%.{0,80}?Cons:\s*([\d.]+)%",
        text,
        flags=re.I | re.S,
    )
    if not cpi:
        cpi = re.search(
            r"CPI \(YoY\) \(Aug\).{0,220}?Act:\s*([\d.]+)%.{0,80}?Cons:\s*([\d.]+)%",
            text,
            flags=re.I | re.S,
        )
    if cpi:
        snap.ea_cpi = _to_float(cpi.group(1))
        snap.calendar.append(
            INVCal(name="EA CPI YoY", actual=snap.ea_cpi, forecast=_to_float(cpi.group(2)), previous=None, unit="percent")
        )
    core = re.search(
        r"Core CPI \(YoY\) \(Aug\).{0,220}?Act:\s*([\d.]+)%",
        text,
        flags=re.I | re.S,
    )
    if core:
        snap.ea_core = _to_float(core.group(1))
    philly = re.search(
        r"Philadelphia Fed Manufacturing Index.{0,220}?Act:\s*([\d.]+)",
        text,
        flags=re.I | re.S,
    )
    if philly:
        snap.philly = _to_float(philly.group(1))
    cftc = re.search(
        r"CFTC EUR speculative net positions.{0,160}?Prev\.:\s*([+-]?[\d.]+)\s*K",
        text,
        flags=re.I | re.S,
    )
    if cftc:
        snap.cftc_eur_k = _to_float(cftc.group(1))


def _parse_related(snap: INVSnapshot, text: str) -> None:
    dxy = re.search(r"Dollar Index.{0,120}?(\d{2,3}\.\d{2})", text, flags=re.I | re.S)
    snap.dxy = _to_float(dxy.group(1) if dxy else None)
    wti = re.search(r"Crude Oil WTI Futures.{0,120}?(\d{2,3}\.\d{2})", text, flags=re.I | re.S)
    snap.wti = _to_float(wti.group(1) if wti else None)
    gold = re.search(r"Gold Futures.{0,120}?([\d,]{4,}\.\d{2})", text, flags=re.I | re.S)
    snap.gold = _to_float(gold.group(1) if gold else None)
    vix = re.search(r"S&P 500 VIX.{0,120}?(\d{1,3}\.\d{2})", text, flags=re.I | re.S)
    snap.vix = _to_float(vix.group(1) if vix else None)


def _parse_news(snap: INVSnapshot, html: str) -> None:
    seen: set[str] = set()
    for match in re.finditer(
        r"\[([^\]]{16,140})\]\((https://www\.investing\.com/(?:news/(?:economy-news|forex-news)|analysis)/[^)]+)\)",
        html,
        flags=re.I,
    ):
        title = html_lib.unescape(match.group(1)).strip()
        low = title.lower()
        if low in seen or any(skip in low for skip in ("ferrari", "touax", "7-eleven")):
            continue
        seen.add(low)
        href = match.group(2)
        source = "Investing.com"
        after = html[match.end() : match.end() + 240]
        byline = re.search(r"\*\s*(Reuters|Investing\.com|Marc Chandler|Trading Point)", after, flags=re.I)
        if byline:
            source = byline.group(1)
        snap.news.append(INVNews(title=title, url=href, source=source))
        if len(snap.news) >= 4:
            break


def fetch_page(timeout: float = 20.0) -> str:
    response = requests.get(PAGE_URL, headers=_UA, timeout=timeout)
    if response.status_code in {202, 403, 429, 503}:
        raise RuntimeError(f"Investing.com blocked ({response.status_code})")
    response.raise_for_status()
    return response.text


def fetch_eurusd_snapshot(*, timeout: float = 20.0, now: datetime | None = None) -> INVSnapshot:
    try:
        html = fetch_page(timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Investing.com EUR/USD fetch failed: {}", exc)
        return INVSnapshot(fetched_at=now or utcnow(), errors=[f"Investing.com fetch failed: {exc}"])
    try:
        return parse_snapshot(html, now=now)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Investing.com EUR/USD parse failed: {}", exc)
        return INVSnapshot(fetched_at=now or utcnow(), errors=[f"Investing.com parse failed: {exc}"])
