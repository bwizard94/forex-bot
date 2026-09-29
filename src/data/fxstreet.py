"""FXStreet EUR/USD forecast, news, and technical page as an intel source.

Public page: https://www.fxstreet.com/currencies/eurusd

The desk reads the pair last, daily technical levels (100-day SMA, Bollinger,
RSI), the fundamental wrap (Fed, ECB, oil, claims, DXY), and the FXStreet
crowd poll. That snapshot feeds the living playbook. It is context — not an
order book. Direct HTTP often hits Cloudflare; parse still works on saved
HTML/markdown, and a blocked fetch never stops the intel cycle.
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

PAGE_URL = "https://www.fxstreet.com/currencies/eurusd"
SOURCE = "FXStreet EUR/USD"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 ForexSentinel/2.8"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "").replace("%", "").replace("$", "").rstrip(".")
    if not text or text in {"n/a", "NA", "—", "-"}:
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
    text = text.replace("\\-", "-")
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
        )
    )


@dataclass(slots=True)
class FXLevel:
    name: str
    price: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FXPoll:
    horizon: str
    bullish: float | None
    bearish: float | None
    sideways: float | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def lean(self) -> str:
        scores = {
            "bullish": self.bullish or 0.0,
            "bearish": self.bearish or 0.0,
            "sideways": self.sideways or 0.0,
        }
        return max(scores, key=scores.get)


@dataclass
class FXSnapshot:
    last: float | None = None
    daily_pct: float | None = None
    lead: str = ""
    technical: str = ""
    fundamental: str = ""
    rsi: float | None = None
    bias: str = ""
    resistance: list[FXLevel] = field(default_factory=list)
    wti: float | None = None
    us10y: float | None = None
    dxy: float | None = None
    dxy_high: float | None = None
    fedwatch_oct_pct: float | None = None
    claims_k: float | None = None
    hicp: float | None = None
    core_hicp: float | None = None
    polls: list[FXPoll] = field(default_factory=list)
    url: str = PAGE_URL
    fetched_at: datetime | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "last": self.last,
            "daily_pct": self.daily_pct,
            "lead": self.lead,
            "technical": self.technical,
            "fundamental": self.fundamental,
            "rsi": self.rsi,
            "bias": self.bias,
            "resistance": [item.as_dict() for item in self.resistance],
            "wti": self.wti,
            "us10y": self.us10y,
            "dxy": self.dxy,
            "dxy_high": self.dxy_high,
            "fedwatch_oct_pct": self.fedwatch_oct_pct,
            "claims_k": self.claims_k,
            "hicp": self.hicp,
            "core_hicp": self.core_hicp,
            "polls": [item.as_dict() for item in self.polls],
            "url": self.url,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "errors": list(self.errors),
            "source": SOURCE,
        }

    def week_poll(self) -> FXPoll | None:
        return next((item for item in self.polls if item.horizon == "1 Week"), None)

    def driver_lines(self) -> list[str]:
        lines: list[str] = []
        if self.last is not None:
            chg = f", day {self.daily_pct:+.2f}%" if self.daily_pct is not None else ""
            lines.append(f"FXStreet EUR/USD last `{self.last:.4f}`{chg} ({PAGE_URL}).")
        if self.bias:
            rsi_bit = f" RSI(14) `{self.rsi:.2f}`." if self.rsi is not None else ""
            lines.append(f"FXStreet daily bias is **{self.bias}**.{rsi_bit}")
        if self.rsi is not None and self.rsi <= 40 and self.bias == "bearish":
            lines.append(
                "FXStreet RSI is stretched oversold on a bearish daily. "
                "Do not short the lower-band bounce — wait for a failed rally into 1.1485/1.1550."
            )
        if self.resistance:
            ladder = ", ".join(f"{item.name} `{item.price:.4f}`" for item in self.resistance[:4])
            lines.append(f"FXStreet resistance: {ladder}. No meaningful supports listed below spot.")
        if self.fedwatch_oct_pct is not None:
            lines.append(
                f"CME FedWatch ~{self.fedwatch_oct_pct:.0f}% chance of another hike in October "
                "— extra Fed tightening caps EUR/USD bounces."
            )
        bits = []
        if self.dxy is not None:
            bits.append(f"DXY `{self.dxy:.2f}`")
        if self.us10y is not None:
            bits.append(f"US 10Y `{self.us10y:.2f}%`")
        if self.wti is not None:
            bits.append(f"WTI `${self.wti:.2f}`")
        if self.claims_k is not None:
            bits.append(f"claims `{self.claims_k:.0f}k`")
        if bits:
            lines.append("FXStreet tape: " + ", ".join(bits) + ".")
        if self.hicp is not None:
            core = f", core {self.core_hicp:.1f}%" if self.core_hicp is not None else ""
            lines.append(f"FXStreet EA HICP {self.hicp:.1f}%{core}.")
        week = self.week_poll()
        if week is not None and week.bearish is not None:
            lines.append(
                f"FXStreet 1-week crowd is {week.bearish:.0f}% bearish / {week.bullish or 0:.0f}% bullish. "
                "Crowd is not a ticket."
            )
        if self.lead:
            lines.append(self.lead[:320])
        return lines[:8]


def parse_snapshot(html: str, *, now: datetime | None = None, url: str = PAGE_URL) -> FXSnapshot:
    """Pull last, TA levels, fundamentals, and crowd polls from the EUR/USD page."""
    snap = FXSnapshot(url=url, fetched_at=now or utcnow())
    if _is_challenge(html):
        snap.errors.append("FXStreet returned a Cloudflare challenge. Live fetch skipped this cycle.")
        return snap
    if not html or len(html) < 200:
        snap.errors.append("FXStreet page was empty.")
        return snap

    text = _plain(html)
    last = re.search(
        r"(?:pair trades around|trades around|EUR/USD(?: is)?(?: trading)? around)\s+(1\.\d{3,5})",
        text,
        flags=re.I,
    )
    if last:
        snap.last = _to_float(last.group(1))
    day = re.search(r"up\s+([\d.]+)%\s+on the day", text, flags=re.I)
    if not day:
        day = re.search(r"down\s+([\d.]+)%\s+on the day", text, flags=re.I)
        snap.daily_pct = -(_to_float(day.group(1)) or 0) if day else None
    else:
        snap.daily_pct = _to_float(day.group(1))

    lead = re.search(
        r"(EUR/USD trades.{20,420}?)(?:\n\n|### Technical)",
        text,
        flags=re.I | re.S,
    )
    if lead:
        snap.lead = re.sub(r"\s+", " ", lead.group(1)).strip()

    tech = re.search(
        r"Technical Analysis\s*(?:EUR/USD\s*)?(.*?)(?:### Fundamental|Fundamental Analysis)",
        text,
        flags=re.I | re.S,
    )
    if tech:
        snap.technical = re.sub(r"\s+", " ", tech.group(1)).strip()[:900]
    if re.search(r"bearish near-term bias|broader downside pressure|bears still control", text, flags=re.I):
        snap.bias = "bearish"
    elif re.search(r"bullish near-term bias|broader upside", text, flags=re.I):
        snap.bias = "bullish"

    rsi = re.search(r"Relative Strength Index\s*\(14\)\s*(?:at|=)\s*([\d.]+)", text, flags=re.I)
    if rsi:
        snap.rsi = _to_float(rsi.group(1))

    levels: list[FXLevel] = []
    for name, pattern in (
        ("former lower BB", r"lower Bollinger band near (1\.\d{3,5})"),
        ("100-day SMA", r"100-day SMA at (1\.\d{3,5})"),
        ("BB middle", r"Bollinger middle band at (1\.\d{3,5})"),
        ("BB upper", r"upper band at (1\.\d{3,5})"),
    ):
        match = re.search(pattern, text, flags=re.I)
        price = _to_float(match.group(1) if match else None)
        if price is not None:
            levels.append(FXLevel(name=name, price=price))
    snap.resistance = levels

    fund = re.search(
        r"Fundamental Analysis\s*(.*?)(?:### 1 Week|About EUR/USD)",
        text,
        flags=re.I | re.S,
    )
    if fund:
        snap.fundamental = re.sub(r"\s+", " ", fund.group(1)).strip()[:1200]

    wti = re.search(r"(?:WTI|West Texas Intermediate)[^\n]{0,80}?\$?\s*([\d.]+)", text, flags=re.I)
    snap.wti = _to_float(wti.group(1) if wti else None)
    ten = re.search(r"10-year US Treasury yield[^\n]{0,60}?around\s+([\d.]+)%", text, flags=re.I)
    snap.us10y = _to_float(ten.group(1) if ten else None)
    dxy = re.search(r"(?:US Dollar Index|\bDXY\b).{0,220}?around\s+([\d.]+)", text, flags=re.I | re.S)
    snap.dxy = _to_float(dxy.group(1) if dxy else None)
    dxy_hi = re.search(r"intraday high of\s+([\d.]+)", text, flags=re.I)
    snap.dxy_high = _to_float(dxy_hi.group(1) if dxy_hi else None)
    fed = re.search(r"(?:FedWatch|around a)\s+([\d.]+)%\s+chance of another rate increase in October", text, flags=re.I)
    if not fed:
        fed = re.search(r"around a\s+([\d.]+)%\s+chance of another", text, flags=re.I)
    snap.fedwatch_oct_pct = _to_float(fed.group(1) if fed else None)
    claims = re.search(r"Initial Jobless Claims fell to\s+([\d.]+)\s*K", text, flags=re.I)
    snap.claims_k = _to_float(claims.group(1) if claims else None)
    hicp = re.search(r"headline HICP was revised slightly lower to\s+([\d.]+)%", text, flags=re.I)
    if not hicp:
        hicp = re.search(r"headline HICP[^\n]{0,40}?([\d.]+)%", text, flags=re.I)
    snap.hicp = _to_float(hicp.group(1) if hicp else None)
    core = re.search(r"core inflation held at\s+([\d.]+)%", text, flags=re.I)
    snap.core_hicp = _to_float(core.group(1) if core else None)

    snap.polls = _parse_polls(text)
    if snap.last is None and not snap.lead and not snap.technical:
        snap.errors.append("Could not read FXStreet EUR/USD last or analysis.")
    return snap


def _parse_polls(text: str) -> list[FXPoll]:
    triples = re.findall(r":\s*([\d.]+)%\s*\n\s*(Bullish|Bearish|Sideways)", text, flags=re.I)
    if len(triples) < 3:
        triples = re.findall(r"([\d.]+)%\s*(?:</[^>]+>\s*)*(Bullish|Bearish|Sideways)", text, flags=re.I)
    labels = ("1 Week", "1 Month", "1 Quarter")
    out: list[FXPoll] = []
    idx = 0
    while idx + 2 < len(triples) and len(out) < 3:
        mapped = {lab.lower(): _to_float(val) for val, lab in triples[idx : idx + 3]}
        out.append(
            FXPoll(
                horizon=labels[len(out)],
                bullish=mapped.get("bullish"),
                bearish=mapped.get("bearish"),
                sideways=mapped.get("sideways"),
            )
        )
        idx += 3
    return [item for item in out if item.bullish is not None or item.bearish is not None]


def fetch_page(timeout: float = 20.0) -> str:
    response = requests.get(PAGE_URL, headers=_UA, timeout=timeout)
    response.raise_for_status()
    return response.text


def fetch_eurusd_snapshot(*, timeout: float = 20.0, now: datetime | None = None) -> FXSnapshot:
    try:
        html = fetch_page(timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        logger.warning("FXStreet EUR/USD fetch failed: {}", exc)
        return FXSnapshot(fetched_at=now or utcnow(), errors=[f"FXStreet fetch failed: {exc}"])
    try:
        return parse_snapshot(html, now=now)
    except Exception as exc:  # noqa: BLE001
        logger.warning("FXStreet EUR/USD parse failed: {}", exc)
        return FXSnapshot(fetched_at=now or utcnow(), errors=[f"FXStreet parse failed: {exc}"])
