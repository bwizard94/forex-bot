"""EUR/USD intelligence: price integrity, news drivers, and macro tape.

The desk uses this snapshot to decide whether quotes are trustworthy,
what could move EUR/USD next, and what to write into the living playbook
and #forex.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from urllib.parse import quote

import requests
from loguru import logger

from src.data.news import CalendarEvent, Headline, NewsBundle, score_sentiment
from src.data.tradingeconomics import TESnapshot
from src.data.fxstreet import FXSnapshot
from src.data.barchart import BCSnapshot
from src.data.investing import INVSnapshot
from src.data.tradingview import TVQuote, TVSnapshot
from src.data.forexfactory import FFSnapshot
from src.utils import price_to_pips, utcnow

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_YAHOO_UA = {
    "User-Agent": "Mozilla/5.0 (compatible; ForexSentinel/2.0; +https://localhost)",
    "Accept": "application/json",
}

MACRO_TICKERS = (
    ("DX-Y.NYB", "DXY", "A rising dollar index usually weighs on EUR/USD."),
    ("^TNX", "US 10Y", "Rising U.S. yields typically bid USD and press EUR/USD."),
    ("^VIX", "VIX", "A VIX spike is risk-off — USD often catches a bid."),
    ("GC=F", "Gold", "Gold up with a softer dollar can support EUR/USD; gold up on stress can coincide with USD demand."),
)

EVENT_REACTIONS: list[tuple[tuple[str, ...], str]] = [
    (
        ("cpi", "consumer price", "inflation", "pce", "core pce"),
        "Inflation prints: hotter than forecast usually bids USD (EUR/USD down); cooler prints can lift EUR/USD.",
    ),
    (
        ("nfp", "non-farm", "nonfarm", "payroll"),
        "Payrolls: a strong beat typically bids USD; a miss can squeeze USD shorts and lift EUR/USD.",
    ),
    (
        ("fomc", "fed funds", "interest rate decision", "powell", "warsh"),
        "Fed: hawkish hold / higher-for-longer bids USD; a dovish cut or ease-later signal lifts EUR/USD.",
    ),
    (
        ("ecb", "lagarde", "refinancing", "deposit facility", "makhlouf", "rehn", "kazaks", "kazaeks", "nagel", "schnabel"),
        "ECB: hawkish language supports EUR; a dovish cut or QT slowdown weighs on EUR/USD.",
    ),
    (
        ("gdp", "growth"),
        "GDP: stronger U.S. growth bids USD; stronger Eurozone growth supports EUR.",
    ),
    (
        ("ppi", "producer price"),
        "PPI often leads CPI. Hot U.S. PPI is USD-positive until the next CPI confirms.",
    ),
    (
        ("retail sales", "retail"),
        "Retail sales: a U.S. beat supports USD; a Eurozone beat supports EUR.",
    ),
    (
        ("ism", "pmi", "ifo", "zew"),
        "PMI/ISM: U.S. strength bids USD; Eurozone strength (Germany IFO/ZEW) supports EUR.",
    ),
    (
        ("jobless", "claims", "unemployment"),
        "Labour: falling U.S. claims / low unemployment bid USD; the inverse can lift EUR/USD.",
    ),
    (
        ("fomc minutes", "beige book"),
        "Fed minutes/Beige Book: watch for dissent on cuts. Hawkish minutes bid USD.",
    ),
    (
        ("brent", "crude", "oil price", "wti", "pipeline"),
        "Energy: a jump in oil can lift Eurozone inflation and complicate the ECB; USD often catches a bid on the first shock.",
    ),
]


@dataclass(slots=True)
class PriceCheck:
    oanda_mid: float | None
    cf_mid: float | None
    m5_close: float | None
    spread_pips: float | None
    oanda_vs_cf_pips: float | None
    oanda_vs_m5_pips: float | None
    stale: bool
    verdict: str
    notes: list[str] = field(default_factory=list)
    te_mid: float | None = None
    oanda_vs_te_pips: float | None = None
    fxs_mid: float | None = None
    oanda_vs_fxs_pips: float | None = None
    bc_mid: float | None = None
    oanda_vs_bc_pips: float | None = None
    inv_mid: float | None = None
    oanda_vs_inv_pips: float | None = None
    tv_mid: float | None = None
    oanda_vs_tv_pips: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MacroPrint:
    symbol: str
    name: str
    last: float | None
    change_pct: float | None
    note: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IntelReport:
    ts: datetime
    price: PriceCheck
    macro: list[MacroPrint]
    events: list[dict[str, Any]]
    headlines: list[dict[str, Any]]
    sentiment: int
    sentiment_label: str
    drivers: list[str]
    stance: str
    notes: list[str]
    h1_bias: str = "neutral"
    d1_bias: str = "neutral"
    te: dict[str, Any] = field(default_factory=dict)
    fxs: dict[str, Any] = field(default_factory=dict)
    bc: dict[str, Any] = field(default_factory=dict)
    inv: dict[str, Any] = field(default_factory=dict)
    tv: dict[str, Any] = field(default_factory=dict)
    tvq: dict[str, Any] = field(default_factory=dict)
    ff: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "price": self.price.as_dict(),
            "macro": [m.as_dict() for m in self.macro],
            "events": self.events,
            "headlines": self.headlines,
            "sentiment": self.sentiment,
            "sentiment_label": self.sentiment_label,
            "drivers": self.drivers,
            "stance": self.stance,
            "notes": self.notes,
            "h1_bias": self.h1_bias,
            "d1_bias": self.d1_bias,
            "te": self.te,
            "fxs": self.fxs,
            "bc": self.bc,
            "inv": self.inv,
            "tv": self.tv,
            "tvq": self.tvq,
            "ff": self.ff,
        }


def typical_eurusd_reaction(title: str) -> str:
    blob = (title or "").lower()
    for keys, text in EVENT_REACTIONS:
        if any(key in blob for key in keys):
            return text
    return (
        "Can move EUR/USD through USD or EUR rates. Stand aside through the print, "
        "then trade the H1 reaction rather than the first tick."
    )


def check_price_consistency(
    *,
    oanda_mid: float | None,
    cf_mid: float | None,
    m5_close: float | None,
    spread: float | None,
    quote_ts: datetime | None,
    warn_pips: float = 8.0,
    now: datetime | None = None,
    te_mid: float | None = None,
    fxs_mid: float | None = None,
    bc_mid: float | None = None,
    inv_mid: float | None = None,
    tv_mid: float | None = None,
    cf_as_of: datetime | None = None,
) -> PriceCheck:
    now = now or utcnow()
    notes: list[str] = []
    oanda_vs_cf = None
    oanda_vs_m5 = None
    oanda_vs_te = None
    oanda_vs_fxs = None
    oanda_vs_bc = None
    oanda_vs_inv = None
    oanda_vs_tv = None
    spread_pips = None
    if oanda_mid is not None and cf_mid is not None:
        oanda_vs_cf = round(price_to_pips("EUR/USD", oanda_mid - cf_mid), 2)
    if oanda_mid is not None and m5_close is not None:
        oanda_vs_m5 = round(price_to_pips("EUR/USD", oanda_mid - m5_close), 2)
    if oanda_mid is not None and te_mid is not None:
        oanda_vs_te = round(price_to_pips("EUR/USD", oanda_mid - te_mid), 2)
    if oanda_mid is not None and fxs_mid is not None:
        oanda_vs_fxs = round(price_to_pips("EUR/USD", oanda_mid - fxs_mid), 2)
    if oanda_mid is not None and bc_mid is not None:
        oanda_vs_bc = round(price_to_pips("EUR/USD", oanda_mid - bc_mid), 2)
    if oanda_mid is not None and inv_mid is not None:
        oanda_vs_inv = round(price_to_pips("EUR/USD", oanda_mid - inv_mid), 2)
    if oanda_mid is not None and tv_mid is not None:
        oanda_vs_tv = round(price_to_pips("EUR/USD", oanda_mid - tv_mid), 2)
    if spread is not None:
        spread_pips = round(price_to_pips("EUR/USD", spread), 2)

    stale = False
    if quote_ts is not None:
        ts = quote_ts if quote_ts.tzinfo else quote_ts.replace(tzinfo=timezone.utc)
        age = (now - ts).total_seconds()
        if age > 90:
            stale = True
            notes.append(f"OANDA quote is {int(age)}s old — treating as stale.")

    if oanda_mid is None:
        notes.append("No live OANDA mid.")
    if cf_mid is None:
        notes.append("No CurrencyFreaks mid to cross-check.")

    cf_age_hours: float | None = None
    if cf_as_of is not None:
        cf_ts = cf_as_of if cf_as_of.tzinfo else cf_as_of.replace(tzinfo=timezone.utc)
        cf_age_hours = max(0.0, (now - cf_ts).total_seconds() / 3600.0)
    cf_stale_daily = bool(
        cf_age_hours is not None
        and (
            cf_age_hours >= 6
            or (
                cf_as_of is not None
                and cf_as_of.hour == 0
                and cf_as_of.minute == 0
                and cf_age_hours >= 1
            )
        )
    )
    live_backers: list[str] = []
    for name, delta in (
        ("M5", oanda_vs_m5),
        ("Trading Economics", oanda_vs_te),
        ("TradingView", oanda_vs_tv),
        ("FXStreet", oanda_vs_fxs),
        ("Barchart", oanda_vs_bc),
        ("Investing.com", oanda_vs_inv),
    ):
        if delta is not None and abs(delta) < warn_pips:
            live_backers.append(name)
    cf_blocks = False

    if oanda_vs_cf is not None:
        if abs(oanda_vs_cf) >= warn_pips:
            oanda_live_ok = len(live_backers) >= 1
            if oanda_live_ok and (cf_stale_daily or (oanda_vs_te is not None and abs(oanda_vs_te) < warn_pips)):
                as_of_txt = cf_as_of.strftime("%Y-%m-%d %H:%M UTC") if cf_as_of else "unknown"
                notes.append(
                    f"OANDA vs CurrencyFreaks {oanda_vs_cf:+.1f} pips, but CF looks like a stale daily "
                    f"print (as of {as_of_txt}). Live prints agree ({', '.join(live_backers)}). "
                    "Not a ticket veto."
                )
            else:
                notes.append(
                    f"OANDA vs CurrencyFreaks {oanda_vs_cf:+.1f} pips (warn ≥ {warn_pips:.0f}). Do not size a new ticket."
                )
                cf_blocks = True
        elif abs(oanda_vs_cf) >= warn_pips * 0.5:
            notes.append(f"OANDA vs CurrencyFreaks {oanda_vs_cf:+.1f} pips — watch, still tradable.")
        else:
            notes.append(f"OANDA and CurrencyFreaks agree within {abs(oanda_vs_cf):.1f} pips.")

    if te_mid is None:
        notes.append("No Trading Economics EUR/USD last this cycle.")
    elif oanda_vs_te is not None:
        if abs(oanda_vs_te) >= warn_pips:
            closer = (
                oanda_vs_cf is not None and abs(oanda_vs_te) < abs(oanda_vs_cf)
            )
            if closer:
                notes.append(
                    f"OANDA vs Trading Economics {oanda_vs_te:+.1f} pips (TE `{te_mid:.5f}`) — closer to OANDA than CurrencyFreaks."
                )
            else:
                notes.append(
                    f"OANDA vs Trading Economics {oanda_vs_te:+.1f} pips (TE `{te_mid:.5f}`). Third print does not back the broker."
                )
        else:
            notes.append(
                f"Trading Economics last `{te_mid:.5f}` is within {abs(oanda_vs_te):.1f} pips of OANDA."
            )
        if oanda_vs_cf is not None and abs(oanda_vs_cf) >= warn_pips:
            if abs(oanda_vs_te) < abs(oanda_vs_cf) and not cf_blocks:
                notes.append(
                    "CurrencyFreaks is the outlier versus Trading Economics. "
                    "Live OANDA is trusted; CF is not a veto."
                )
            elif abs(oanda_vs_te) < abs(oanda_vs_cf) and cf_blocks:
                notes.append(
                    "CurrencyFreaks is the outlier versus Trading Economics. Still skip new tickets until CF reconverges."
                )
            elif cf_mid is not None:
                te_vs_cf = round(price_to_pips("EUR/USD", te_mid - cf_mid), 2)
                if abs(te_vs_cf) <= abs(oanda_vs_te):
                    notes.append(
                        "Trading Economics agrees with CurrencyFreaks — OANDA is the outlier. Stay flat."
                    )
                    cf_blocks = True

    if fxs_mid is None:
        notes.append("No FXStreet EUR/USD last this cycle.")
    elif oanda_vs_fxs is not None:
        if abs(oanda_vs_fxs) >= warn_pips:
            notes.append(
                f"OANDA vs FXStreet {oanda_vs_fxs:+.1f} pips (FXS `{fxs_mid:.5f}`). Fourth print — context only."
            )
        else:
            notes.append(
                f"FXStreet last `{fxs_mid:.5f}` is within {abs(oanda_vs_fxs):.1f} pips of OANDA."
            )

    if bc_mid is None:
        notes.append("No Barchart ^EURUSD last this cycle.")
    elif oanda_vs_bc is not None:
        if abs(oanda_vs_bc) >= warn_pips:
            notes.append(
                f"OANDA vs Barchart {oanda_vs_bc:+.1f} pips (BC `{bc_mid:.5f}`). Fifth print — context only."
            )
        else:
            notes.append(
                f"Barchart last `{bc_mid:.5f}` is within {abs(oanda_vs_bc):.1f} pips of OANDA."
            )

    if inv_mid is None:
        notes.append("No Investing.com EUR/USD last this cycle.")
    elif oanda_vs_inv is not None:
        if abs(oanda_vs_inv) >= warn_pips:
            notes.append(
                f"OANDA vs Investing.com {oanda_vs_inv:+.1f} pips (INV `{inv_mid:.5f}`). Sixth print — context only."
            )
        else:
            notes.append(
                f"Investing.com last `{inv_mid:.5f}` is within {abs(oanda_vs_inv):.1f} pips of OANDA."
            )

    if tv_mid is None:
        notes.append("No TradingView EURUSD last this cycle.")
    elif oanda_vs_tv is not None:
        if abs(oanda_vs_tv) >= warn_pips:
            notes.append(
                f"OANDA vs TradingView {oanda_vs_tv:+.1f} pips (TV `{tv_mid:.5f}`). Seventh print — context only."
            )
        else:
            notes.append(
                f"TradingView last `{tv_mid:.5f}` is within {abs(oanda_vs_tv):.1f} pips of OANDA."
            )

    if oanda_vs_m5 is not None and abs(oanda_vs_m5) >= 8:
        notes.append(f"Live mid is {oanda_vs_m5:+.1f} pips from the last M5 close — tape has jumped.")

    if spread_pips is not None:
        if spread_pips >= 3.5:
            notes.append(f"Spread {spread_pips:.1f} pips is wide for EUR/USD — skip until it compresses.")
        else:
            notes.append(f"Spread {spread_pips:.1f} pips is usable.")

    verdict = "consistent"
    if oanda_mid is None or (oanda_vs_cf is None and cf_mid is None):
        verdict = "watch"
    if stale:
        verdict = "watch"
    if spread_pips is not None and spread_pips >= 3.5:
        verdict = "watch"
    if cf_blocks:
        verdict = "disagree"
    if spread_pips is not None and spread_pips >= 6:
        verdict = "disagree"

    if not notes:
        notes.append("Not enough quotes yet to judge integrity.")
        verdict = "watch"
    return PriceCheck(
        oanda_mid=oanda_mid,
        cf_mid=cf_mid,
        m5_close=m5_close,
        spread_pips=spread_pips,
        oanda_vs_cf_pips=oanda_vs_cf,
        oanda_vs_m5_pips=oanda_vs_m5,
        stale=stale,
        verdict=verdict,
        notes=notes,
        te_mid=te_mid,
        oanda_vs_te_pips=oanda_vs_te,
        fxs_mid=fxs_mid,
        oanda_vs_fxs_pips=oanda_vs_fxs,
        bc_mid=bc_mid,
        oanda_vs_bc_pips=oanda_vs_bc,
        inv_mid=inv_mid,
        oanda_vs_inv_pips=oanda_vs_inv,
        tv_mid=tv_mid,
        oanda_vs_tv_pips=oanda_vs_tv,
    )


def fetch_yahoo_last(symbol: str, timeout: float = 10.0) -> tuple[float | None, float | None]:
    url = YAHOO_CHART.format(symbol=quote(symbol, safe=""))
    response = requests.get(url, params={"interval": "1d", "range": "5d"}, headers=_YAHOO_UA, timeout=timeout)
    response.raise_for_status()
    result = (response.json().get("chart") or {}).get("result") or []
    if not result:
        return None, None
    meta = result[0].get("meta") or {}
    last = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if last is None:
        closes = ((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        closes = [c for c in closes if c is not None]
        last = closes[-1] if closes else None
        prev = closes[-2] if len(closes) >= 2 else prev
    last_f = float(last) if last is not None else None
    prev_f = float(prev) if prev is not None else None
    change = None
    if last_f is not None and prev_f:
        change = 100.0 * (last_f - prev_f) / prev_f
    return last_f, change


def fetch_macro_tape() -> list[MacroPrint]:
    out: list[MacroPrint] = []
    for ticker, name, note in MACRO_TICKERS:
        try:
            last, change = fetch_yahoo_last(ticker)
            out.append(MacroPrint(symbol=ticker, name=name, last=last, change_pct=change, note=note))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Macro tape {} failed: {}", ticker, exc)
            out.append(MacroPrint(symbol=ticker, name=name, last=None, change_pct=None, note=note))
    return out


def _sentiment_label(score: int) -> str:
    if score >= 2:
        return "Bullish EUR/USD"
    if score <= -2:
        return "Bearish EUR/USD"
    if score > 0:
        return "Mildly bullish"
    if score < 0:
        return "Mildly bearish"
    return "Mixed / two-way"


def analyze_drivers(
    events: list[CalendarEvent],
    headlines: list[Headline],
    macro: list[MacroPrint],
    now: datetime | None = None,
    te: TESnapshot | None = None,
    fxs: FXSnapshot | None = None,
    bc: BCSnapshot | None = None,
    inv: INVSnapshot | None = None,
    tv: TVSnapshot | None = None,
    tvq: TVQuote | None = None,
    ff: FFSnapshot | None = None,
) -> list[str]:
    now = now or utcnow()
    horizon = now + timedelta(hours=36)
    drivers: list[str] = []
    for event in events:
        if event.ts is None:
            continue
        ts = event.ts if event.ts.tzinfo else event.ts.replace(tzinfo=timezone.utc)
        if not (now - timedelta(hours=2) <= ts <= horizon):
            continue
        if event.impact not in {"High", "Medium"}:
            continue
        when = ts.strftime("%H:%M UTC %d %b")
        drivers.append(
            f"{when} {event.country} {event.impact} {event.title} — {typical_eurusd_reaction(event.title)}"
        )
        if len(drivers) >= 6:
            break
    if not drivers:
        drivers.append("No medium/high EUR or USD prints in the next 36 hours. Focus on H1 trend and DXY.")

    for item in macro:
        if item.last is None or item.change_pct is None:
            continue
        direction = "up" if item.change_pct >= 0 else "down"
        drivers.append(
            f"{item.name} is {direction} {abs(item.change_pct):.2f}% at {item.last:.3f}. {item.note}"
        )

    news_blob = " ".join(h.title for h in headlines[:8])
    score = score_sentiment(news_blob)
    if score >= 2:
        drivers.append("Headline keywords lean toward a higher EUR/USD (softer USD / firmer EUR).")
    elif score <= -2:
        drivers.append("Headline keywords lean toward a lower EUR/USD (firmer USD / softer EUR).")
    if te is not None:
        for line in te.driver_lines()[:5]:
            if line not in drivers:
                drivers.append(line)
    if fxs is not None:
        for line in fxs.driver_lines()[:5]:
            if line not in drivers:
                drivers.append(line)
    if bc is not None:
        for line in bc.driver_lines()[:6]:
            if line not in drivers:
                drivers.append(line)
    if inv is not None:
        for line in inv.driver_lines()[:5]:
            if line not in drivers:
                drivers.append(line)
    if tvq is not None:
        for line in tvq.driver_lines()[:5]:
            if line not in drivers:
                drivers.append(line)
    if tv is not None:
        for line in tv.driver_lines()[:3]:
            if line not in drivers:
                drivers.append(line)
    if ff is not None:
        for line in ff.driver_lines()[:6]:
            if line not in drivers:
                drivers.append(line)
    return drivers[:36]


def compose_stance(
    *,
    h1_bias: str,
    d1_bias: str,
    sentiment: int,
    price: PriceCheck,
    macro: list[MacroPrint],
    te: TESnapshot | None = None,
    fxs: FXSnapshot | None = None,
    bc: BCSnapshot | None = None,
    inv: INVSnapshot | None = None,
    tv: TVSnapshot | None = None,
    tvq: TVQuote | None = None,
    ff: FFSnapshot | None = None,
) -> str:
    if price.verdict == "disagree":
        extra = ""
        if price.te_mid is not None and price.oanda_vs_te_pips is not None:
            extra = f" Trading Economics last `{price.te_mid:.5f}` ({price.oanda_vs_te_pips:+.1f} pips vs OANDA)."
        if price.fxs_mid is not None and price.oanda_vs_fxs_pips is not None:
            extra += f" FXStreet last `{price.fxs_mid:.5f}` ({price.oanda_vs_fxs_pips:+.1f} pips vs OANDA)."
        if price.bc_mid is not None and price.oanda_vs_bc_pips is not None:
            extra += f" Barchart last `{price.bc_mid:.5f}` ({price.oanda_vs_bc_pips:+.1f} pips vs OANDA)."
        if price.inv_mid is not None and price.oanda_vs_inv_pips is not None:
            extra += f" Investing.com last `{price.inv_mid:.5f}` ({price.oanda_vs_inv_pips:+.1f} pips vs OANDA)."
        if price.tv_mid is not None and price.oanda_vs_tv_pips is not None:
            extra += f" TradingView last `{price.tv_mid:.5f}` ({price.oanda_vs_tv_pips:+.1f} pips vs OANDA)."
        return (
            "FLAT — quotes disagree. No new EUR/USD tickets until OANDA and CurrencyFreaks reconverge."
            + extra
        )
    dxy = next((m for m in macro if m.name == "DXY" and m.change_pct is not None), None)
    dollar = "firmer" if dxy and (dxy.change_pct or 0) > 0.15 else "softer" if dxy and (dxy.change_pct or 0) < -0.15 else "mixed"
    if h1_bias == d1_bias == "bearish":
        core = "Primary hunt: EUR/USD shorts with the H1/D1 downtrend."
    elif h1_bias == d1_bias == "bullish":
        core = "Primary hunt: EUR/USD longs with the H1/D1 uptrend."
    elif h1_bias == "bearish":
        core = "H1 is bearish — prefer fades of M5 rallies, do not chase longs."
    elif h1_bias == "bullish":
        core = "H1 is bullish — prefer discounted longs, do not chase shorts."
    else:
        if d1_bias == "bearish":
            core = "H1 is flat under a bearish D1 — fade M5 rallies, do not chase longs."
        elif d1_bias == "bullish":
            core = "H1 is flat under a bullish D1 — buy discounted dips, do not chase shorts."
        else:
            core = "H1 is flat — only a stretched M5 fade or a strong continuation is allowed."
    news = _sentiment_label(sentiment)
    te_bit = ""
    if te is not None and te.yearly_pct is not None:
        if te.yearly_pct <= -1 and h1_bias == "bearish":
            te_bit = " TE yearly tape is still a weaker euro — do not fade that with a TE 1.16/1.18 recovery model."
        elif te.yearly_pct >= 1 and h1_bias == "bullish":
            te_bit = " TE yearly tape is a firmer euro."
        elif te.quarter_forecast is not None and te.last is not None and h1_bias == "bearish":
            if te.quarter_forecast - te.last >= 0.008:
                te_bit = (
                    f" TE models `{te.quarter_forecast:.2f}` by quarter-end vs spot `{te.last:.4f}` "
                    "— that forecast is not a reason to buy against H1."
                )
    fxs_bit = ""
    if fxs is not None and fxs.bias == "bearish" and fxs.rsi is not None and fxs.rsi <= 40:
        fxs_bit = (
            f" FXStreet daily is still bearish with RSI `{fxs.rsi:.1f}` — "
            "do not short the lower-band bounce; fade rips into 1.1485/1.1550 instead."
        )
    elif fxs is not None and fxs.bias == "bearish" and h1_bias == "bearish":
        fxs_bit = " FXStreet daily tape is still bearish."
    bc_bit = ""
    if bc is not None:
        specs = bc.specs_net()
        crowded = specs is not None and specs < 0
        strong_sell = "sell" in (bc.opinion or "").lower() and (
            (bc.opinion_pct or 0) >= 60 or "strong" in (bc.opinion or "").lower()
        )
        if strong_sell and (bc.near_day_low() or crowded):
            s1 = f" first real support is S1 `{bc.s1:.5f}`." if bc.s1 is not None else " wait for a failed rally into R1."
            pct = f"{bc.opinion_pct:.0f}%" if bc.opinion_pct is not None else ""
            crowd = " Specs already net short." if crowded else ""
            bc_bit = (
                f" Barchart {pct} {bc.opinion} is not a license to chase the day low.{crowd}"
                f" Do not pile in;{s1}"
            )
        elif strong_sell and h1_bias == "bearish":
            bc_bit = f" Barchart opinion is {bc.opinion}."
    inv_bit = ""
    if inv is not None and inv.stacked_sell():
        inv_bit = (
            " Investing.com daily+weekly technicals are Strong Sell — "
            "same crowded-sell tape as Barchart; do not chase the day low."
        )
    elif inv is not None and "sell" in (inv.summary or inv.ta_daily or "").lower() and h1_bias == "bearish":
        inv_bit = f" Investing.com summary is {inv.summary or inv.ta_daily}."
    tvq_bit = ""
    if tvq is not None and tvq.stacked_sell():
        month = " with 1M Neutral" if tvq.month_neutral() else ""
        trap = ""
        if tvq.crowd_buy_at_lows():
            lo = f"`{tvq.buy_zone_low:.4f}`" if tvq.buy_zone_low is not None else "1.1480"
            trap = f" Crowd BUY at {lo} is the washout trap."
        tvq_bit = (
            f" TradingView technicals are {tvq.ta_today or 'Sell'} today and 1W {tvq.ta_week or 'Sell'}"
            f"{month} — that is not a new downtrend and not a license to short the washout.{trap}"
        )
    elif tvq is not None and (tvq.ta_today or tvq.ta_week):
        tvq_bit = (
            f" TradingView technicals: today {tvq.ta_today or 'n/a'}, "
            f"1W {tvq.ta_week or 'n/a'}, 1M {tvq.ta_month or 'n/a'}."
        )
    tv_bit = ""
    if tv is not None:
        kept = ", ".join((tv.kept or [])[:3])
        extra = f" Catalog kept {kept}." if kept else ""
        tv_bit = (
            " TradingView hunt uses Supertrend, squeeze, VWAP, Donchian sweeps, and WaveTrend"
            " — stacked Sell at an RSI/WaveTrend washout is still not a short."
            + extra
        )
    ff_bit = ""
    if ff is not None:
        nxt = ff.next_high()
        if nxt is not None and nxt.ts is not None:
            ts = nxt.ts if nxt.ts.tzinfo else nxt.ts.replace(tzinfo=timezone.utc)
            ff_bit = (
                f" Forex Factory next red print is {nxt.country} {nxt.title} "
                f"at {ts.strftime('%H:%M UTC')} — blackout, not a ticket."
            )
    return f"{core} Dollar tape is {dollar}. News read: {news}.{te_bit}{fxs_bit}{bc_bit}{inv_bit}{tvq_bit}{tv_bit}{ff_bit}"


def build_intel_report(
    *,
    price: PriceCheck,
    bundle: NewsBundle,
    macro: list[MacroPrint],
    h1_bias: str = "neutral",
    d1_bias: str = "neutral",
    now: datetime | None = None,
    te: TESnapshot | None = None,
    fxs: FXSnapshot | None = None,
    bc: BCSnapshot | None = None,
    inv: INVSnapshot | None = None,
    tv: TVSnapshot | None = None,
    tvq: TVQuote | None = None,
    ff: FFSnapshot | None = None,
) -> IntelReport:
    now = now or utcnow()
    news_blob = " ".join(h.title for h in bundle.headlines) + " " + " ".join(e.title for e in bundle.events)
    if te is not None:
        news_blob += " " + " ".join(item.title for item in te.news) + " " + (te.summary or "")
    if fxs is not None:
        news_blob += " " + (fxs.lead or "") + " " + (fxs.fundamental or "")
    if bc is not None:
        news_blob += " " + " ".join(item.title + " " + item.body for item in bc.news)
    if inv is not None:
        news_blob += " " + " ".join(item.title for item in inv.news)
    if ff is not None:
        news_blob += " " + " ".join(item.title for item in ff.news)
        news_blob += " " + " ".join(item.title for item in ff.events)
    sentiment = score_sentiment(news_blob)
    events = []
    for event in bundle.events:
        if event.ts is None or event.impact not in {"High", "Medium"}:
            continue
        ts = event.ts if event.ts.tzinfo else event.ts.replace(tzinfo=timezone.utc)
        if ts < now - timedelta(hours=6) or ts > now + timedelta(hours=48):
            continue
        row = event.as_dict()
        row["typical_reaction"] = typical_eurusd_reaction(event.title)
        events.append(row)
        if len(events) >= 8:
            break
    headlines = [h.as_dict() for h in bundle.headlines[:8]]
    if te is not None:
        for item in te.news[:4]:
            if any(existing.get("title") == item.title for existing in headlines):
                continue
            headlines.insert(
                0,
                {"title": item.title, "source": "Trading Economics EUR/USD", "url": item.url, "published": item.published},
            )
        headlines = headlines[:10]
    if fxs is not None and fxs.lead:
        headlines.insert(
            0,
            {
                "title": fxs.lead[:180],
                "source": "FXStreet EUR/USD",
                "url": fxs.url,
                "published": None,
            },
        )
        headlines = headlines[:10]
    if bc is not None and bc.news:
        headlines.insert(
            0,
            {
                "title": bc.news[0].title,
                "source": "Barchart ^EURUSD",
                "url": bc.news[0].url or bc.url,
                "published": None,
            },
        )
        headlines = headlines[:10]
    if inv is not None and inv.news:
        headlines.insert(
            0,
            {
                "title": inv.news[0].title,
                "source": "Investing.com EUR/USD",
                "url": inv.news[0].url or inv.url,
                "published": None,
            },
        )
        headlines = headlines[:10]
    if ff is not None and ff.news:
        headlines.insert(
            0,
            {
                "title": ff.news[0].title,
                "source": "Forex Factory EUR/USD",
                "url": ff.news[0].url or ff.url,
                "published": None,
            },
        )
        headlines = headlines[:10]
    drivers = analyze_drivers(
        bundle.events, bundle.headlines, macro, now=now, te=te, fxs=fxs, bc=bc, inv=inv, tv=tv, tvq=tvq, ff=ff
    )
    notes = list(price.notes)
    if bundle.errors:
        notes.extend(f"Feed: {err}" for err in bundle.errors[:4])
    if te is not None:
        notes.extend(f"TE: {err}" for err in te.errors[:3])
    if fxs is not None:
        notes.extend(f"FXStreet: {err}" for err in fxs.errors[:3])
    if bc is not None:
        notes.extend(f"Barchart: {err}" for err in bc.errors[:3])
    if inv is not None:
        notes.extend(f"Investing.com: {err}" for err in inv.errors[:3])
    if tv is not None:
        notes.extend(f"TradingView: {err}" for err in tv.errors[:3])
    if tvq is not None:
        notes.extend(f"TradingView EURUSD: {err}" for err in tvq.errors[:3])
    if ff is not None:
        notes.extend(f"Forex Factory: {err}" for err in ff.errors[:3])
    stance = compose_stance(
        h1_bias=h1_bias,
        d1_bias=d1_bias,
        sentiment=sentiment,
        price=price,
        macro=macro,
        te=te,
        fxs=fxs,
        bc=bc,
        inv=inv,
        tv=tv,
        tvq=tvq,
        ff=ff,
    )
    return IntelReport(
        ts=now,
        price=price,
        macro=macro,
        events=events,
        headlines=headlines,
        sentiment=sentiment,
        sentiment_label=_sentiment_label(sentiment),
        drivers=drivers,
        stance=stance,
        notes=notes,
        h1_bias=h1_bias,
        d1_bias=d1_bias,
        te=te.as_dict() if te is not None else {},
        fxs=fxs.as_dict() if fxs is not None else {},
        bc=bc.as_dict() if bc is not None else {},
        inv=inv.as_dict() if inv is not None else {},
        tv=tv.as_dict() if tv is not None else {},
        tvq=tvq.as_dict() if tvq is not None else {},
        ff=ff.as_dict() if ff is not None else {},
    )
