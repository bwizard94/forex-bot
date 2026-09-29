"""TradingView EUR/USD memory: symbol hub (seventh print) + scripts catalog.

Public pages:

- https://www.tradingview.com/symbols/EURUSD/  — last, TV technical ratings,
  performance ladder, volatility, community idea levels
- https://www.tradingview.com/scripts/          — hunt-tool catalog

The desk does not copy Pine blindly. It skims both pages, keeps facts that
fit this EUR/USD book, stores them in ``desk/TRADINGVIEW.md``, and actually
runs the mapped tools (Supertrend, TTM Squeeze, session VWAP, Donchian
sweep, Ichimoku, WaveTrend, TMA, EWMAC) on OANDA bars.

The symbol last is a **seventh print** — context only. TV Sell today + 1W
Sell with 1M Neutral is not a new downtrend. A stacked Sell / crowd BUY at
the day-low washout is still not a ticket. A blocked fetch never stops the
intel cycle — standing hunt ideas still apply.
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

PAGE_URL = "https://www.tradingview.com/scripts/"
SYMBOL_URL = "https://www.tradingview.com/symbols/EURUSD/"
SOURCE = "TradingView community scripts"
QUOTE_SOURCE = "TradingView EURUSD"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 ForexSentinel/2.13"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Ideas this EUR/USD specialist actually hunts with. Catalog cards that
# match these stay in memory; the rest are noted and discarded.
KEEP_HINTS = (
    "reaction path",
    "tma",
    "triangular",
    "liquidity sweep",
    "ewmac",
    "contrarian",
    "support resistance",
    "volume spike",
    "delta run",
    "linear regression",
    "auto trendline",
    "liquidity heatmap",
    "heatmap",
    "sweep radar",
    "body fractal",
    "marketmind",
    "structure break",
    "choch",
    "tbr stats",
    "quarterly break",
    "supertrend",
    "squeeze",
    "vwap",
    "ichimoku",
    "wavetrend",
    "donchian",
    "keltner",
    "chandelier",
)

SKIP_HINTS = (
    "gex",
    "liquidation",
    "gold m15",
    "xau",
    "lorentzian",
    "sector breadth",
    "rth gap",
    "expected move",
    "zcash",
    "zec",
    "sniperfusion",
    "forward move",
)

# Always-on mapping from the community catalog onto this hunt.
HUNT_IDEAS = (
    {
        "name": "Reaction Path / fair price",
        "use": (
            "Session VWAP is fair price. Continuation only when price is beyond "
            "VWAP with Supertrend/EWMAC; stretched >1.8 ATR is a reaction, not a chase."
        ),
    },
    {
        "name": "Colored TMA",
        "use": "TMA slope as a slow trend. Do not chase when price is already far from TMA.",
    },
    {
        "name": "ICT liquidity sweep",
        "use": (
            "Donchian wick-through then close back inside is a sweep. Wait for the "
            "retest. Still never short the RSI/WaveTrend washout."
        ),
    },
    {
        "name": "EWMAC",
        "use": "Volatility-normalized EMA spread sizes trend strength for continuation.",
    },
    {
        "name": "Contrarian Zones",
        "use": "Stacked oscillator extremes are exhaustion. Not a license to chase the day low.",
    },
    {
        "name": "S/R confluence",
        "use": "Prior-day high/low + Donchian + VWAP, read with Barchart S1/R1.",
    },
    {
        "name": "Volume Spike Radar",
        "use": "OANDA tick-volume z vs range: expansion participates; absorption does not.",
    },
    {
        "name": "Supertrend + TTM Squeeze + Ichimoku + WaveTrend",
        "use": (
            "Community classics on every M5 bar. Squeeze-on waits for the fire. "
            "WaveTrend ≤ −53 is the same washout rule as RSI ≤ 40."
        ),
    },
)


TA_SCORE = r"(Strong\s+Sell|Strong\s+Buy|Neutral|Sell|Buy)"


def _to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "").replace("%", "").replace("$", "").rstrip(".")
    text = text.replace("\\", "").replace("−", "-").replace("–", "-")
    if not text or text in {"n/a", "NA", "N/A", "—", "-", "–"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _norm_ta(raw: str | None) -> str:
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw).strip().title()


def _plain(blob: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", blob)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = text.replace("**", "")
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


def _keep(title: str, summary: str) -> bool:
    title_l = (title or "").lower()
    blob = f"{title} {summary}".lower()
    # Skip only from the title so a misaligned card blurb cannot poison a keeper.
    if any(hint in title_l for hint in SKIP_HINTS):
        return False
    return any(hint in blob for hint in KEEP_HINTS)


@dataclass(slots=True)
class TVScript:
    title: str
    url: str = ""
    summary: str = ""
    keep: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TVSnapshot:
    fetched_at: datetime | None = None
    url: str = PAGE_URL
    scripts: list[TVScript] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    hunt: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "url": self.url,
            "scripts": [item.as_dict() for item in self.scripts],
            "kept": list(self.kept),
            "skipped": list(self.skipped),
            "hunt": list(self.hunt),
            "errors": list(self.errors),
        }

    def driver_lines(self) -> list[str]:
        lines: list[str] = []
        if self.kept:
            lines.append(
                "TradingView catalog kept: "
                + "; ".join(self.kept[:6])
                + ". Mapped onto Supertrend / squeeze / VWAP / Donchian sweep / WaveTrend."
            )
        else:
            lines.append(
                "TradingView hunt still uses Supertrend, TTM squeeze, session VWAP, "
                "Donchian sweeps, Ichimoku, WaveTrend, TMA, EWMAC even if the catalog fetch is empty."
            )
        if self.errors:
            lines.append(f"TradingView catalog: {self.errors[0]}")
        return lines


def parse_snapshot(html: str, *, now: datetime | None = None) -> TVSnapshot:
    snap = TVSnapshot(fetched_at=now or utcnow(), hunt=[item["name"] for item in HUNT_IDEAS])
    if _is_challenge(html):
        snap.errors.append("TradingView returned a Cloudflare challenge. Live catalog skipped this cycle.")
        return snap
    blob = html or ""
    if len(_plain(blob)) < 80:
        snap.errors.append("TradingView scripts page was empty.")
        return snap

    cards: list[TVScript] = []
    title_iter = list(
        re.finditer(
            r'data-qa-id="ui-lib-card-link-title"[^>]*>(.*?)</a>',
            blob,
            flags=re.S,
        )
    )
    para_iter = list(
        re.finditer(
            r'data-qa-id="ui-lib-card-link-paragraph"[^>]*>.*?<span class="line-clamp-content[^"]*">(.*?)</span>',
            blob,
            flags=re.S,
        )
    )
    urls = re.findall(r"https://www\.tradingview\.com/script/[A-Za-z0-9]+-[^\"'#\s]+", blob)
    seen_urls: list[str] = []
    for url in urls:
        clean = url.rstrip("/")
        if clean not in seen_urls:
            seen_urls.append(clean)

    if title_iter:
        for i, match in enumerate(title_iter):
            title = _plain(match.group(1))
            if not title or title.lower() in {"popular", "marketplace", "editors' picks", "get started"}:
                continue
            summary = _plain(para_iter[i].group(1)) if i < len(para_iter) else ""
            url = seen_urls[i] if i < len(seen_urls) else PAGE_URL
            cards.append(
                TVScript(
                    title=title[:160],
                    url=url,
                    summary=summary[:400],
                    keep=_keep(title, summary),
                )
            )
    else:
        # Markdown / stripped HTML fallback: "Title [Author] blurb"
        md = _plain(blob)
        found = re.findall(
            r"((?:[A-Z][^\[\n]{6,90})\[[^\]]+\])\s+(.{80,360})",
            md,
        )
        used_urls = set()
        for title, summary in found:
            title = title.strip()
            url = next((u for u in seen_urls if u not in used_urls), PAGE_URL)
            if url != PAGE_URL:
                used_urls.add(url)
            cards.append(
                TVScript(
                    title=title[:160],
                    url=url,
                    summary=_plain(summary)[:400],
                    keep=_keep(title, summary),
                )
            )
        if not cards and seen_urls:
            for url in seen_urls:
                slug = url.rstrip("/").split("/")[-1]
                name = re.sub(r"^[A-Za-z0-9]+-", "", slug).replace("-", " ")
                cards.append(TVScript(title=name[:160], url=url, summary="", keep=_keep(name, "")))

    # De-dupe by title.
    unique: dict[str, TVScript] = {}
    for card in cards:
        key = card.title.strip().lower()
        if key and key not in unique:
            unique[key] = card
    snap.scripts = list(unique.values())
    snap.kept = [item.title for item in snap.scripts if item.keep]
    snap.skipped = [item.title for item in snap.scripts if not item.keep]
    if not snap.scripts:
        snap.errors.append("Could not read TradingView script cards.")
    return snap


def fetch_scripts_snapshot(*, timeout: float = 18.0, now: datetime | None = None) -> TVSnapshot:
    now = now or utcnow()
    try:
        response = requests.get(PAGE_URL, headers=_UA, timeout=timeout)
        if response.status_code >= 400:
            raise RuntimeError(f"TradingView blocked ({response.status_code})")
        return parse_snapshot(response.text, now=now)
    except Exception as exc:
        logger.warning("TradingView scripts fetch failed: {}", exc)
        snap = TVSnapshot(
            fetched_at=now,
            hunt=[item["name"] for item in HUNT_IDEAS],
            errors=[f"TradingView fetch failed: {exc}"],
        )
        return snap


def _idea_bias(title: str) -> str:
    blob = (title or "").lower()
    buy = any(token in blob for token in ("buy", "long", "rebound"))
    sell = any(token in blob for token in ("sell", "bearish", "short", "breakdown", "rejection"))
    if buy and not sell:
        return "buy"
    if sell and not buy:
        return "sell"
    return "mixed"


@dataclass(slots=True)
class TVIdea:
    title: str
    url: str = ""
    bias: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TVQuote:
    last: float | None = None
    daily_pct: float | None = None
    day_low: float | None = None
    day_high: float | None = None
    open: float | None = None
    ta_today: str = ""
    ta_week: str = ""
    ta_month: str = ""
    volatility_pct: float | None = None
    pct_1d: float | None = None
    pct_5d: float | None = None
    pct_1m: float | None = None
    pct_6m: float | None = None
    pct_ytd: float | None = None
    pct_1y: float | None = None
    pct_5y: float | None = None
    pct_10y: float | None = None
    pct_all: float | None = None
    buy_zone_low: float | None = None
    buy_zone_high: float | None = None
    support: float | None = None
    resistance_low: float | None = None
    resistance_high: float | None = None
    target_1560: float | None = None
    ideas: list[TVIdea] = field(default_factory=list)
    market_closed: bool = False
    url: str = SYMBOL_URL
    fetched_at: datetime | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "last": self.last,
            "daily_pct": self.daily_pct,
            "day_low": self.day_low,
            "day_high": self.day_high,
            "open": self.open,
            "ta_today": self.ta_today,
            "ta_week": self.ta_week,
            "ta_month": self.ta_month,
            "volatility_pct": self.volatility_pct,
            "pct_1d": self.pct_1d,
            "pct_5d": self.pct_5d,
            "pct_1m": self.pct_1m,
            "pct_6m": self.pct_6m,
            "pct_ytd": self.pct_ytd,
            "pct_1y": self.pct_1y,
            "pct_5y": self.pct_5y,
            "pct_10y": self.pct_10y,
            "pct_all": self.pct_all,
            "buy_zone_low": self.buy_zone_low,
            "buy_zone_high": self.buy_zone_high,
            "support": self.support,
            "resistance_low": self.resistance_low,
            "resistance_high": self.resistance_high,
            "target_1560": self.target_1560,
            "ideas": [item.as_dict() for item in self.ideas],
            "market_closed": self.market_closed,
            "url": self.url,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "errors": list(self.errors),
            "source": QUOTE_SOURCE,
        }

    def stacked_sell(self) -> bool:
        return "sell" in (self.ta_today or "").lower() and "sell" in (self.ta_week or "").lower()

    def month_neutral(self) -> bool:
        return "neutral" in (self.ta_month or "").lower()

    def crowd_buy_at_lows(self) -> bool:
        if any(item.bias == "buy" for item in self.ideas):
            return True
        return self.buy_zone_low is not None

    def driver_lines(self) -> list[str]:
        lines: list[str] = []
        if self.last is not None:
            chg = f", 1d {self.pct_1d:+.2f}%" if self.pct_1d is not None else ""
            vol = f", vol {self.volatility_pct:.2f}%" if self.volatility_pct is not None else ""
            lines.append(f"TradingView EURUSD last `{self.last:.5f}`{chg}{vol} ({SYMBOL_URL}).")
        ta_bits = [bit for bit in (self.ta_today, self.ta_week, self.ta_month) if bit]
        if ta_bits:
            today = self.ta_today or "n/a"
            week = self.ta_week or "n/a"
            month = self.ta_month or "n/a"
            extra = (
                " 1M Neutral means do not treat Sell as a new downtrend."
                if self.month_neutral()
                else ""
            )
            lines.append(
                f"TradingView technicals: today {today}, 1W {week}, 1M {month}."
                " Stacked Sell is not a license to short the washout."
                + extra
            )
        if self.pct_5d is not None or self.pct_1y is not None:
            bits = []
            if self.pct_5d is not None:
                bits.append(f"5d {self.pct_5d:+.2f}%")
            if self.pct_1m is not None:
                bits.append(f"1m {self.pct_1m:+.2f}%")
            if self.pct_ytd is not None:
                bits.append(f"YTD {self.pct_ytd:+.2f}%")
            if self.pct_1y is not None:
                bits.append(f"1y {self.pct_1y:+.2f}%")
            lines.append("TradingView performance: " + ", ".join(bits) + ".")
        zone = ""
        if self.buy_zone_low is not None and self.buy_zone_high is not None:
            zone = f" Crowd BUY zone `{self.buy_zone_low:.4f}`–`{self.buy_zone_high:.4f}` is the washout trap."
        ladder = []
        if self.support is not None:
            ladder.append(f"support `{self.support:.4f}`")
        if self.resistance_low is not None:
            top = (
                f"–`{self.resistance_high:.4f}`"
                if self.resistance_high is not None
                else ""
            )
            ladder.append(f"resistance `{self.resistance_low:.4f}`{top}")
        if self.target_1560 is not None:
            ladder.append(f"1.1560 support `{self.target_1560:.4f}`")
        if zone or ladder:
            mix = " Community ideas are mixed."
            if ladder:
                mix += " " + ", ".join(ladder) + "."
            lines.append(mix.strip() + zone)
        elif any(item.bias == "buy" for item in self.ideas) and any(
            item.bias == "sell" for item in self.ideas
        ):
            lines.append(
                "TradingView community ideas are mixed (crowd BUY vs bearish continuation). "
                "Neither is a ticket at the day-low washout."
            )
        if self.market_closed:
            lines.append(
                "TradingView showed a Market closed badge — widget state, not a desk halt."
            )
        if self.errors:
            lines.append(f"TradingView EURUSD: {self.errors[0]}")
        return lines[:8]


def parse_quote(html: str, *, now: datetime | None = None, url: str = SYMBOL_URL) -> TVQuote:
    snap = TVQuote(url=url, fetched_at=now or utcnow())
    if _is_challenge(html):
        snap.errors.append("TradingView returned a Cloudflare challenge. Live EURUSD quote skipped this cycle.")
        return snap
    blob = html or ""
    text = _plain(blob)
    if len(text) < 80:
        snap.errors.append("TradingView EURUSD page was empty.")
        return snap

    faq = re.search(r"current rate of EURUSD is\s+(1\.\d{4,5})", blob + " " + text, flags=re.I)
    if faq:
        snap.last = _to_float(faq.group(1))
    if snap.last is None:
        trade = re.search(r'"trade"\s*:\s*\{\s*"price"\s*:\s*(1\.\d{4,5})', blob)
        if trade:
            snap.last = _to_float(trade.group(1))
    bar = re.search(
        r'"daily_bar"\s*:\s*\{[^}]*"close"\s*:\s*"(1\.\d{4,5})"[^}]*'
        r'"high"\s*:\s*"(1\.\d{4,5})"[^}]*"low"\s*:\s*"(1\.\d{4,5})"[^}]*'
        r'"open"\s*:\s*"(1\.\d{4,5})"',
        blob,
    )
    if not bar:
        bar = re.search(
            r'"daily_bar"\s*:\s*\{[^}]*"high"\s*:\s*"(1\.\d{4,5})"[^}]*'
            r'"low"\s*:\s*"(1\.\d{4,5})"[^}]*"open"\s*:\s*"(1\.\d{4,5})"[^}]*'
            r'"close"\s*:\s*"(1\.\d{4,5})"',
            blob,
        )
        if bar:
            snap.day_high = snap.day_high or _to_float(bar.group(1))
            snap.day_low = snap.day_low or _to_float(bar.group(2))
            snap.open = snap.open or _to_float(bar.group(3))
            snap.last = snap.last or _to_float(bar.group(4))
            bar = None
    if bar:
        snap.last = snap.last or _to_float(bar.group(1))
        snap.day_high = _to_float(bar.group(2))
        snap.day_low = _to_float(bar.group(3))
        snap.open = _to_float(bar.group(4))
    if snap.last is None:
        loose = re.search(r'"price"\s*:\s*(1\.\d{4,5})', blob)
        if loose:
            snap.last = _to_float(loose.group(1))

    today = re.search(
        rf"technical rating for the pair is\s+{TA_SCORE}\s+today",
        text,
        flags=re.I,
    )
    if today:
        snap.ta_today = _norm_ta(today.group(1))
    week = re.search(
        rf"1 week rating the EURUSD shows the\s+{TA_SCORE}\s+signal",
        text,
        flags=re.I,
    )
    if week:
        snap.ta_week = _norm_ta(week.group(1))
    month = re.search(rf"1 month rating is\s+{TA_SCORE}", text, flags=re.I)
    if month:
        snap.ta_month = _norm_ta(month.group(1))

    vol = re.search(r"volatility rating of\s+([\d.]+)\s*%", text, flags=re.I)
    if vol:
        snap.volatility_pct = _to_float(vol.group(1))

    perf = re.search(
        r"1 day\s+([−+\-]?\d+(?:\.\d+)?)%\s+5 days\s+([−+\-]?\d+(?:\.\d+)?)%\s+"
        r"1 month\s+([−+\-]?\d+(?:\.\d+)?)%\s+6 months\s+([−+\-]?\d+(?:\.\d+)?)%\s+"
        r"Year to date\s+([−+\-]?\d+(?:\.\d+)?)%\s+1 year\s+([−+\-]?\d+(?:\.\d+)?)%\s+"
        r"5 years\s+([−+\-]?\d+(?:\.\d+)?)%\s+10 years\s+([−+\-]?\d+(?:\.\d+)?)%\s+"
        r"All time\s+([−+\-]?\d+(?:\.\d+)?)%",
        text,
        flags=re.I,
    )
    if perf:
        snap.pct_1d = _to_float(perf.group(1))
        snap.pct_5d = _to_float(perf.group(2))
        snap.pct_1m = _to_float(perf.group(3))
        snap.pct_6m = _to_float(perf.group(4))
        snap.pct_ytd = _to_float(perf.group(5))
        snap.pct_1y = _to_float(perf.group(6))
        snap.pct_5y = _to_float(perf.group(7))
        snap.pct_10y = _to_float(perf.group(8))
        snap.pct_all = _to_float(perf.group(9))
        snap.daily_pct = snap.pct_1d

    zone = re.search(
        r"Buy Zone:\s*(1\.\d{3,5})\s*[–\-]\s*(1\.\d{3,5})",
        text,
        flags=re.I,
    )
    if zone:
        snap.buy_zone_low = _to_float(zone.group(1))
        snap.buy_zone_high = _to_float(zone.group(2))
    res = re.search(
        r"(1\.\d{3,5})\s*[–\-]\s*(1\.\d{3,5})\s+area has turned into an important resistance",
        text,
        flags=re.I,
    )
    if res:
        snap.resistance_low = _to_float(res.group(1))
        snap.resistance_high = _to_float(res.group(2))
    if snap.resistance_low is None:
        res2 = re.search(r"Toward\s+(1\.158\d)", text, flags=re.I)
        if res2:
            snap.resistance_low = _to_float(res2.group(1))
    sup = re.search(
        r"(1\.\d{3,5})\s+area remains the key support",
        text,
        flags=re.I,
    )
    if sup:
        snap.support = _to_float(sup.group(1))
    tgt = re.search(r"Targets\s+(1\.156\d)\s+Support", text, flags=re.I)
    if tgt:
        snap.target_1560 = _to_float(tgt.group(1))

    seen: dict[str, TVIdea] = {}
    for match in re.finditer(
        r"https://www\.tradingview\.com/chart/EURUSD/([A-Za-z0-9]+)-([^/\"'#\s]+)",
        blob,
    ):
        slug = match.group(2).replace("-", " ").strip()
        title = re.sub(r"\s+", " ", slug)
        if not title or title.lower() in seen:
            continue
        url = f"https://www.tradingview.com/chart/EURUSD/{match.group(1)}-{match.group(2)}"
        seen[title.lower()] = TVIdea(title=title[:160], url=url, bias=_idea_bias(title))
    snap.ideas = list(seen.values())[:12]
    snap.market_closed = bool(re.search(r"title=\"Market closed\"|Market closed", blob, flags=re.I))

    if snap.last is None:
        snap.errors.append("Could not read a TradingView EURUSD last.")
    return snap


def fetch_eurusd_quote(*, timeout: float = 18.0, now: datetime | None = None) -> TVQuote:
    now = now or utcnow()
    try:
        response = requests.get(SYMBOL_URL, headers=_UA, timeout=timeout)
        if response.status_code >= 400:
            raise RuntimeError(f"TradingView blocked ({response.status_code})")
        return parse_quote(response.text, now=now)
    except Exception as exc:
        logger.warning("TradingView EURUSD fetch failed: {}", exc)
        return TVQuote(
            fetched_at=now,
            errors=[f"TradingView EURUSD fetch failed: {exc}"],
        )
