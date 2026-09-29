"""Living EUR/USD playbook and append-only learning log.

These files sit in ``desk/`` so the specialist can reread its own notes
on the next cycle and so a human can watch the book grow.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from src.analysis.intel import IntelReport
from src.config import get_settings
from src.utils import utcnow

ROOT = Path(__file__).resolve().parents[2]
DESK_DIR = ROOT / "desk"
PLAYBOOK_PATH = DESK_DIR / "EURUSD_PLAYBOOK.md"
LEARNING_LOG_PATH = DESK_DIR / "LEARNING_LOG.md"
GROWTH_PATH = DESK_DIR / "GROWTH.md"
HISTORY_PATH = DESK_DIR / "HISTORY.md"
TE_PATH = DESK_DIR / "TRADINGECONOMICS.md"
FXS_PATH = DESK_DIR / "FXSTREET.md"
BC_PATH = DESK_DIR / "BARCHART.md"
INV_PATH = DESK_DIR / "INVESTING.md"
TV_PATH = DESK_DIR / "TRADINGVIEW.md"
FF_PATH = DESK_DIR / "FOREXFACTORY.md"
MT4_PATH = DESK_DIR / "MT4.md"
OPS_PATH = DESK_DIR / "OPERATING.md"
SCALP_PATH = DESK_DIR / "SCALPING.md"
MISTAKES_PATH = DESK_DIR / "MISTAKES.md"
SHEETS_PATH = DESK_DIR / "SHEETS.md"
NEWS_PATH = DESK_DIR / "NEWS.md"
NEWS_PATTERNS_PATH = DESK_DIR / "NEWS_PATTERNS.md"
MAX_LOG_CHARS = 180_000


def ensure_desk_dir() -> Path:
    DESK_DIR.mkdir(parents=True, exist_ok=True)
    return DESK_DIR


def read_playbook() -> str:
    if PLAYBOOK_PATH.exists():
        return PLAYBOOK_PATH.read_text(encoding="utf-8")
    return ""


def read_learning_log() -> str:
    if LEARNING_LOG_PATH.exists():
        return LEARNING_LOG_PATH.read_text(encoding="utf-8")
    return ""


def read_growth() -> str:
    if GROWTH_PATH.exists():
        return GROWTH_PATH.read_text(encoding="utf-8")
    return ""


def read_history() -> str:
    if HISTORY_PATH.exists():
        return HISTORY_PATH.read_text(encoding="utf-8")
    return ""


def read_tradingeconomics() -> str:
    if TE_PATH.exists():
        return TE_PATH.read_text(encoding="utf-8")
    return ""


def read_fxstreet() -> str:
    if FXS_PATH.exists():
        return FXS_PATH.read_text(encoding="utf-8")
    return ""


def read_barchart() -> str:
    if BC_PATH.exists():
        return BC_PATH.read_text(encoding="utf-8")
    return ""


def read_investing() -> str:
    if INV_PATH.exists():
        return INV_PATH.read_text(encoding="utf-8")
    return ""


def read_tradingview() -> str:
    if TV_PATH.exists():
        return TV_PATH.read_text(encoding="utf-8")
    return ""


def read_forexfactory() -> str:
    if FF_PATH.exists():
        return FF_PATH.read_text(encoding="utf-8")
    return ""


def read_mt4() -> str:
    if MT4_PATH.exists():
        return MT4_PATH.read_text(encoding="utf-8")
    return ""


def read_operating() -> str:
    if OPS_PATH.exists():
        return OPS_PATH.read_text(encoding="utf-8")
    return ""


def read_scalping() -> str:
    if SCALP_PATH.exists():
        return SCALP_PATH.read_text(encoding="utf-8")
    return ""


def read_mistakes() -> str:
    if MISTAKES_PATH.exists():
        return MISTAKES_PATH.read_text(encoding="utf-8")
    return ""


def read_sheets() -> str:
    if SHEETS_PATH.exists():
        return SHEETS_PATH.read_text(encoding="utf-8")
    return ""


def read_news() -> str:
    if NEWS_PATH.exists():
        return NEWS_PATH.read_text(encoding="utf-8")
    return ""


def read_news_patterns() -> str:
    if NEWS_PATTERNS_PATH.exists():
        return NEWS_PATTERNS_PATH.read_text(encoding="utf-8")
    return ""


def _clip_log(text: str) -> str:
    if len(text) <= MAX_LOG_CHARS:
        return text
    marker = "\n## "
    idx = text.find(marker, len(text) - MAX_LOG_CHARS)
    if idx == -1:
        return text[-MAX_LOG_CHARS:]
    return "# EUR/USD learning log\n\n_Older entries were trimmed._\n" + text[idx:]


def append_learning(title: str, bullets: Iterable[str], *, ts: datetime | None = None) -> None:
    ensure_desk_dir()
    ts = ts or utcnow()
    lines = [f"## {ts.strftime('%Y-%m-%d %H:%M UTC')} — {title}"]
    for item in bullets:
        text = str(item).strip()
        if text:
            lines.append(f"- {text}")
    lines.append("")
    existing = read_learning_log()
    if not existing.strip():
        existing = "# EUR/USD learning log\n\nDated notes the desk appends after intel, fills, and losses.\n\n"
    PLAYBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEARNING_LOG_PATH.write_text(_clip_log(existing + "\n".join(lines) + "\n"), encoding="utf-8")


def _te_lines(intel: IntelReport) -> list[str]:
    te = intel.te or {}
    if not te:
        return [
            "- Trading Economics euro-area/currency was not fetched this cycle.",
            "- Source: https://tradingeconomics.com/euro-area/currency",
        ]
    lines = [
        "- Source: [tradingeconomics.com/euro-area/currency](https://tradingeconomics.com/euro-area/currency)",
    ]
    last = te.get("last")
    if last is not None:
        bits = [f"- Last: `{float(last):.5f}`"]
        if te.get("daily_pct") is not None:
            bits[0] += f"  day `{float(te['daily_pct']):+.2f}%`"
        if te.get("monthly_pct") is not None:
            bits[0] += f"  month `{float(te['monthly_pct']):+.2f}%`"
        if te.get("yearly_pct") is not None:
            bits[0] += f"  year `{float(te['yearly_pct']):+.2f}%`"
        lines.extend(bits)
    q = te.get("quarter_forecast")
    y = te.get("year_forecast")
    forecasts = te.get("forecasts") or []
    if q is not None or y is not None or forecasts:
        ladder = ", ".join(f"{float(v):.2f}" for v in forecasts) if forecasts else ""
        q_txt = f"`{float(q):.2f}` this quarter" if q is not None else "n/a this quarter"
        y_txt = f"`{float(y):.2f}` in 12 months" if y is not None else "n/a in 12 months"
        extra = f" (TEForecast {ladder})" if ladder else ""
        lines.append(f"- Models: {q_txt}, {y_txt}{extra}. Not a license to fade H1.")
    for item in (te.get("related") or [])[:6]:
        if not isinstance(item, dict) or item.get("last") is None:
            continue
        prev = f" (prev {item.get('previous')})" if item.get("previous") is not None else ""
        ref = f" · {item.get('reference')}" if item.get("reference") else ""
        lines.append(f"- **{item.get('name')}** `{item.get('last')}`{prev}{ref}. {item.get('note') or ''}".rstrip())
    for item in (te.get("crosses") or [])[:5]:
        if not isinstance(item, dict) or not item.get("symbol"):
            continue
        last_x = item.get("last")
        day = item.get("day_pct")
        year = item.get("year_pct")
        last_txt = f"{float(last_x):.4f}" if last_x is not None else "n/a"
        day_txt = f" {float(day):+.2f}%" if day is not None else ""
        year_txt = f" / year {float(year):+.2f}%" if year is not None else ""
        lines.append(f"- Cross `{item['symbol']}` `{last_txt}`{day_txt}{year_txt}")
    if te.get("summary"):
        lines.append(f"- Tape: {str(te['summary'])[:360]}")
    for item in (te.get("news") or [])[:3]:
        if isinstance(item, dict) and item.get("title"):
            lines.append(f"- News: {item['title']}")
    for err in te.get("errors") or []:
        lines.append(f"- Fetch note: {err}")
    return lines or ["- Trading Economics snapshot was empty this cycle."]


def _fxs_lines(intel: IntelReport) -> list[str]:
    fxs = intel.fxs or {}
    if not fxs:
        return [
            "- FXStreet EUR/USD was not fetched this cycle.",
            "- Source: https://www.fxstreet.com/currencies/eurusd",
        ]
    lines = [
        "- Source: [fxstreet.com/currencies/eurusd](https://www.fxstreet.com/currencies/eurusd)",
    ]
    last = fxs.get("last")
    if last is not None:
        bits = [f"- Last: `{float(last):.5f}`"]
        if fxs.get("daily_pct") is not None:
            bits[0] += f"  day `{float(fxs['daily_pct']):+.2f}%`"
        lines.extend(bits)
    if fxs.get("bias") or fxs.get("rsi") is not None:
        rsi = f"`{float(fxs['rsi']):.2f}`" if fxs.get("rsi") is not None else "n/a"
        lines.append(f"- Daily bias: **{fxs.get('bias') or 'n/a'}**. RSI(14) {rsi}.")
    for item in (fxs.get("resistance") or [])[:4]:
        if isinstance(item, dict) and item.get("price") is not None:
            lines.append(f"- Resistance **{item.get('name')}** `{float(item['price']):.4f}`")
    extras = []
    if fxs.get("dxy") is not None:
        extras.append(f"DXY `{float(fxs['dxy']):.2f}`")
    if fxs.get("us10y") is not None:
        extras.append(f"US 10Y `{float(fxs['us10y']):.2f}%`")
    if fxs.get("wti") is not None:
        extras.append(f"WTI `${float(fxs['wti']):.2f}`")
    if fxs.get("fedwatch_oct_pct") is not None:
        extras.append(f"FedWatch Oct `{float(fxs['fedwatch_oct_pct']):.0f}%`")
    if extras:
        lines.append("- Tape: " + " · ".join(extras))
    if fxs.get("claims_k") is not None:
        lines.append(f"- Jobless claims: `{float(fxs['claims_k']):.0f}k`. A beat typically bids USD.")
    if fxs.get("hicp") is not None:
        core = f", core `{float(fxs['core_hicp']):.1f}%`" if fxs.get("core_hicp") is not None else ""
        lines.append(f"- EA HICP `{float(fxs['hicp']):.1f}%`{core}.")
    for poll in (fxs.get("polls") or [])[:3]:
        if not isinstance(poll, dict):
            continue
        lines.append(
            f"- Crowd {poll.get('horizon')}: "
            f"bull {poll.get('bullish')}% / bear {poll.get('bearish')}% / side {poll.get('sideways')}%. Not a ticket."
        )
    if fxs.get("lead"):
        lines.append(f"- Tape: {str(fxs['lead'])[:360]}")
    if fxs.get("technical"):
        lines.append(f"- TA: {str(fxs['technical'])[:360]}")
    for err in fxs.get("errors") or []:
        lines.append(f"- Fetch note: {err}")
    return lines or ["- FXStreet snapshot was empty this cycle."]


def _bc_lines(intel: IntelReport) -> list[str]:
    bc = intel.bc or {}
    if not bc:
        return [
            "- Barchart ^EURUSD was not fetched this cycle.",
            "- Source: https://www.barchart.com/forex/quotes/%5EEURUSD",
        ]
    lines = [
        "- Source: [barchart.com/forex/quotes/^EURUSD](https://www.barchart.com/forex/quotes/%5EEURUSD)",
    ]
    last = bc.get("last")
    if last is not None:
        bits = [f"- Last: `{float(last):.5f}`"]
        if bc.get("daily_pct") is not None:
            bits[0] += f"  day `{float(bc['daily_pct']):+.2f}%`"
        if bc.get("day_low") is not None and bc.get("day_high") is not None:
            bits[0] += f"  range `{float(bc['day_low']):.5f}`–`{float(bc['day_high']):.5f}`"
        lines.extend(bits)
    if bc.get("opinion") or bc.get("opinion_pct") is not None:
        pct = f"{float(bc['opinion_pct']):.0f}% {bc.get('opinion_side') or ''}".strip() if bc.get("opinion_pct") is not None else "n/a"
        lines.append(
            f"- Opinion: **{bc.get('opinion') or 'n/a'}** ({pct}). "
            "Not a ticket to short the day low."
        )
    if bc.get("s1") is not None:
        ladder = []
        for key, name in (("r3", "R3"), ("r2", "R2"), ("r1", "R1"), ("s1", "S1"), ("s2", "S2"), ("s3", "S3")):
            if bc.get(key) is not None:
                ladder.append(f"{name} `{float(bc[key]):.5f}`")
        lines.append("- Daily pivots: " + ", ".join(ladder) + ". S1 is the first real support.")
    if bc.get("fib_382") is not None or bc.get("high_52w") is not None:
        fibs = []
        if bc.get("high_52w") is not None:
            fibs.append(f"high `{float(bc['high_52w']):.5f}`")
        if bc.get("fib_618") is not None:
            fibs.append(f"61.8% `{float(bc['fib_618']):.5f}`")
        if bc.get("fib_50") is not None:
            fibs.append(f"50% `{float(bc['fib_50']):.5f}`")
        if bc.get("fib_382") is not None:
            fibs.append(f"38.2% `{float(bc['fib_382']):.5f}`")
        if bc.get("low_52w") is not None:
            fibs.append(f"low `{float(bc['low_52w']):.5f}`")
        off = f" ({float(bc['high_52w_pct']):+.2f}% vs high)" if bc.get("high_52w_pct") is not None else ""
        lines.append(f"- 52w fibs{off}: " + ", ".join(fibs) + ". Spot is below all of them.")
    specs = next((item for item in (bc.get("cot") or []) if isinstance(item, dict) and "non-commercial" in str(item.get("name", "")).lower()), None)
    if specs and specs.get("net") is not None:
        as_of = f" as of {bc.get('cot_as_of')}" if bc.get("cot_as_of") else ""
        direction = "net short" if specs["net"] < 0 else "net long"
        lines.append(
            f"- COT specs{as_of}: L `{specs.get('long')}` / S `{specs.get('short')}` ({direction} {abs(int(specs['net'])):,}). "
            "Do not pile into a crowded short."
        )
    perf = []
    if bc.get("five_day_pct") is not None:
        perf.append(f"5d `{float(bc['five_day_pct']):+.2f}%`")
    if bc.get("perf_1m") is not None:
        perf.append(f"1M `{float(bc['perf_1m']):+.2f}%`")
    if bc.get("perf_3m") is not None:
        perf.append(f"3M `{float(bc['perf_3m']):+.2f}%`")
    if bc.get("perf_52w") is not None:
        perf.append(f"52w `{float(bc['perf_52w']):+.2f}%`")
    if bc.get("relative_strength") is not None:
        perf.append(f"RS `{float(bc['relative_strength']):.2f}`")
    if perf:
        lines.append("- Performance: " + " · ".join(perf))
    related = []
    if bc.get("dxy") is not None:
        related.append(f"DXY `{float(bc['dxy']):.2f}`")
    if bc.get("fxe") is not None:
        related.append(f"FXE `{float(bc['fxe']):.2f}`")
    if bc.get("euro_fx_fut") is not None:
        related.append(f"E6 `{float(bc['euro_fx_fut']):.5f}`")
    if related:
        lines.append("- Related: " + " · ".join(related))
    for item in (bc.get("news") or [])[:2]:
        if isinstance(item, dict) and item.get("title"):
            lines.append(f"- News: {item['title']}")
    for err in bc.get("errors") or []:
        lines.append(f"- Fetch note: {err}")
    return lines or ["- Barchart snapshot was empty this cycle."]


def _inv_lines(intel: IntelReport) -> list[str]:
    inv = intel.inv or {}
    if not inv:
        return [
            "- Investing.com EUR/USD was not fetched this cycle.",
            "- Source: https://www.investing.com/currencies/eur-usd",
        ]
    lines = [
        "- Source: [investing.com/currencies/eur-usd](https://www.investing.com/currencies/eur-usd)",
    ]
    last = inv.get("last")
    if last is not None:
        bits = [f"- Last: `{float(last):.5f}`"]
        if inv.get("daily_pct") is not None:
            bits[0] += f"  day `{float(inv['daily_pct']):+.2f}%`"
        if inv.get("day_low") is not None and inv.get("day_high") is not None:
            bits[0] += f"  range `{float(inv['day_low']):.4f}`–`{float(inv['day_high']):.4f}`"
        lines.extend(bits)
    if inv.get("bid") is not None and inv.get("ask") is not None:
        lines.append(f"- Bid/ask: `{float(inv['bid']):.4f}` / `{float(inv['ask']):.4f}`")
    ta = []
    for key, label in (
        ("ta_hourly", "H1"),
        ("ta_daily", "D1"),
        ("ta_weekly", "W"),
        ("ta_monthly", "M"),
    ):
        if inv.get(key):
            ta.append(f"{label} **{inv[key]}**")
    if inv.get("summary") or ta:
        summary = inv.get("summary") or ""
        extra = f" Summary **{summary}**." if summary else ""
        lines.append("- Technicals: " + (", ".join(ta) if ta else "n/a") + extra + " Not a ticket to short the washout.")
    if inv.get("cme_last") is not None:
        lines.append(f"- CME euro futures `{float(inv['cme_last']):.4f}`. Fade zone near Barchart R1, not a breakout buy.")
    if inv.get("cftc_eur_k") is not None:
        lines.append(
            f"- CFTC EUR specs `{float(inv['cftc_eur_k']):+.1f}k` net. "
            "Crowded short — same read as Barchart COT."
        )
    cal = []
    if inv.get("claims_k") is not None:
        vs = f" vs `{float(inv['claims_cons_k']):.0f}k`" if inv.get("claims_cons_k") is not None else ""
        cal.append(f"claims `{float(inv['claims_k']):.0f}k`{vs}")
    if inv.get("ea_cpi") is not None:
        core = f" / core `{float(inv['ea_core']):.1f}%`" if inv.get("ea_core") is not None else ""
        cal.append(f"EA CPI `{float(inv['ea_cpi']):.1f}%`{core}")
    if inv.get("housing_m") is not None:
        cal.append(f"housing `{float(inv['housing_m']):.3f}M`")
    if cal:
        lines.append("- Calendar: " + " · ".join(cal))
    if inv.get("year_pct") is not None:
        lines.append(f"- 1-year `{float(inv['year_pct']):+.2f}%`. Weaker-euro tape — do not buy TE 1.16 against H1.")
    related = []
    if inv.get("dxy") is not None:
        related.append(f"DXY `{float(inv['dxy']):.2f}`")
    if inv.get("wti") is not None:
        related.append(f"WTI `${float(inv['wti']):.2f}`")
    if inv.get("gold") is not None:
        related.append(f"gold `{float(inv['gold']):.0f}`")
    if related:
        lines.append("- Tape: " + " · ".join(related))
    for item in (inv.get("news") or [])[:3]:
        if isinstance(item, dict) and item.get("title"):
            lines.append(f"- News: {item['title']}")
    for err in inv.get("errors") or []:
        lines.append(f"- Fetch note: {err}")
    return lines or ["- Investing.com snapshot was empty this cycle."]


def _ff_lines(intel: IntelReport) -> list[str]:
    ff = intel.ff or {}
    if not ff:
        return [
            "- Forex Factory EUR/USD market hub was not fetched this cycle.",
            "- Source: https://www.forexfactory.com/market/eurusd",
        ]
    lines = [
        "- Source: [forexfactory.com/market/eurusd](https://www.forexfactory.com/market/eurusd)",
        "- Pair news reference. A headline is **not** a ticket. Red prints still sit behind the ±30 minute blackout.",
    ]
    last = ff.get("last")
    if last is not None:
        lines.append(f"- Last: `{float(last):.5f}` (context only; OANDA is the fill).")
    for item in (ff.get("events") or [])[:4]:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        when = item.get("ts") or ""
        if when and "T" in when:
            when = when[11:16] + " UTC"
        impact = item.get("impact") or ""
        country = item.get("country") or ""
        lines.append(f"- Calendar: **{impact}** {country} {item['title']}" + (f" `{when}`" if when else ""))
    for item in (ff.get("news") or [])[:5]:
        if isinstance(item, dict) and item.get("title"):
            lines.append(f"- News: {item['title']}")
    for err in ff.get("errors") or []:
        lines.append(f"- Fetch note: {err}")
    return lines or ["- Forex Factory snapshot was empty this cycle."]


def _tvq_lines(intel: IntelReport) -> list[str]:
    tvq = intel.tvq or {}
    if not tvq:
        return [
            "- TradingView EURUSD hub was not fetched this cycle.",
            "- Source: https://www.tradingview.com/symbols/EURUSD/",
            "- Seventh print is context only. Sell today + 1W Sell with 1M Neutral is not a new downtrend.",
        ]
    lines = [
        "- Source: [tradingview.com/symbols/EURUSD](https://www.tradingview.com/symbols/EURUSD/)",
    ]
    if tvq.get("last") is not None:
        last = float(tvq["last"])
        chg = tvq.get("pct_1d")
        vol = tvq.get("volatility_pct")
        extra = f", 1d {chg:+.2f}%" if chg is not None else ""
        extra += f", vol {vol:.2f}%" if vol is not None else ""
        lines.append(f"- Last: `{last:.5f}`{extra} (seventh print, context only).")
    ta_today = tvq.get("ta_today") or ""
    ta_week = tvq.get("ta_week") or ""
    ta_month = tvq.get("ta_month") or ""
    if ta_today or ta_week or ta_month:
        lines.append(
            f"- Technicals: today **{ta_today or 'n/a'}**, 1W **{ta_week or 'n/a'}**, "
            f"1M **{ta_month or 'n/a'}**. Stacked Sell is not a washout short. "
            "1M Neutral means do not treat Sell as a new downtrend."
        )
    perf = []
    for key, label in (
        ("pct_5d", "5d"),
        ("pct_1m", "1m"),
        ("pct_ytd", "YTD"),
        ("pct_1y", "1y"),
    ):
        val = tvq.get(key)
        if val is not None:
            perf.append(f"{label} {float(val):+.2f}%")
    if perf:
        lines.append("- Performance: " + ", ".join(perf) + ".")
    lo, hi = tvq.get("buy_zone_low"), tvq.get("buy_zone_high")
    if lo is not None and hi is not None:
        lines.append(
            f"- Crowd BUY zone `{float(lo):.4f}`–`{float(hi):.4f}` is the washout trap — do not buy it and do not fade it as a ticket."
        )
    ladder = []
    if tvq.get("support") is not None:
        ladder.append(f"support `{float(tvq['support']):.4f}`")
    if tvq.get("resistance_low") is not None:
        top = (
            f"–`{float(tvq['resistance_high']):.4f}`"
            if tvq.get("resistance_high") is not None
            else ""
        )
        ladder.append(f"resistance `{float(tvq['resistance_low']):.4f}`{top}")
    if ladder:
        lines.append("- Community levels: " + ", ".join(ladder) + ".")
    ideas = tvq.get("ideas") or []
    titles = [item.get("title") for item in ideas if isinstance(item, dict) and item.get("title")]
    if titles:
        lines.append("- Ideas: " + "; ".join(str(t) for t in titles[:6]))
    if tvq.get("market_closed"):
        lines.append("- Market-closed badge is widget state, not a desk halt.")
    for err in tvq.get("errors") or []:
        lines.append(f"- Fetch note: {err}")
    return lines


def _tv_lines(intel: IntelReport) -> list[str]:
    tv = intel.tv or {}
    if not tv:
        return [
            "- TradingView scripts catalog was not fetched this cycle.",
            "- Source: https://www.tradingview.com/scripts/",
            "- Hunt still uses Supertrend, TTM squeeze, session VWAP, Donchian sweeps, Ichimoku, WaveTrend, TMA, EWMAC.",
        ]
    lines = [
        "- Source: [tradingview.com/scripts](https://www.tradingview.com/scripts/)",
    ]
    hunt = tv.get("hunt") or []
    if hunt:
        lines.append("- Hunt memory: " + "; ".join(str(item) for item in hunt[:8]))
    kept = tv.get("kept") or []
    if kept:
        lines.append("- Catalog kept: " + "; ".join(str(item) for item in kept[:8]))
    skipped = tv.get("skipped") or []
    if skipped:
        lines.append(
            "- Discarded (not this EUR/USD book): " + "; ".join(str(item) for item in skipped[:6])
        )
    lines.append(
        "- Live tools: Supertrend, TTM squeeze, session VWAP (fair price), Donchian "
        "liquidity sweeps, Ichimoku Kumo, WaveTrend, TMA stretch, EWMAC strength. "
        "Squeeze-on or stretch from fair price blocks a chase. WaveTrend ≤ −53 is the same washout as RSI ≤ 40."
    )
    for err in tv.get("errors") or []:
        lines.append(f"- Fetch note: {err}")
    return lines


def render_playbook(
    *,
    intel: IntelReport,
    lessons: list[dict[str, Any]] | None = None,
    journals: list[dict[str, Any]] | None = None,
    open_trades: list[dict[str, Any]] | None = None,
    extra_rules: list[str] | None = None,
) -> str:
    lessons = lessons or []
    journals = journals or []
    open_trades = open_trades or []
    extra_rules = extra_rules or []
    settings = get_settings()
    px = intel.price
    price_lines = []
    if px.oanda_mid is not None:
        price_lines.append(f"- OANDA mid: `{px.oanda_mid:.5f}`")
    if px.cf_mid is not None:
        price_lines.append(f"- CurrencyFreaks mid: `{px.cf_mid:.5f}`")
    if px.m5_close is not None:
        price_lines.append(f"- Last M5 close: `{px.m5_close:.5f}`")
    if px.oanda_vs_cf_pips is not None:
        price_lines.append(f"- OANDA vs CurrencyFreaks: `{px.oanda_vs_cf_pips:+.1f}` pips")
    if px.spread_pips is not None:
        price_lines.append(f"- Spread: `{px.spread_pips:.1f}` pips")
    if px.te_mid is not None:
        price_lines.append(f"- Trading Economics last: `{px.te_mid:.5f}`")
    if px.oanda_vs_te_pips is not None:
        price_lines.append(f"- OANDA vs Trading Economics: `{px.oanda_vs_te_pips:+.1f}` pips")
    if px.fxs_mid is not None:
        price_lines.append(f"- FXStreet last: `{px.fxs_mid:.5f}`")
    if px.oanda_vs_fxs_pips is not None:
        price_lines.append(f"- OANDA vs FXStreet: `{px.oanda_vs_fxs_pips:+.1f}` pips")
    if px.bc_mid is not None:
        price_lines.append(f"- Barchart last: `{px.bc_mid:.5f}`")
    if px.oanda_vs_bc_pips is not None:
        price_lines.append(f"- OANDA vs Barchart: `{px.oanda_vs_bc_pips:+.1f}` pips")
    if px.inv_mid is not None:
        price_lines.append(f"- Investing.com last: `{px.inv_mid:.5f}`")
    if px.oanda_vs_inv_pips is not None:
        price_lines.append(f"- OANDA vs Investing.com: `{px.oanda_vs_inv_pips:+.1f}` pips")
    if px.tv_mid is not None:
        price_lines.append(f"- TradingView last: `{px.tv_mid:.5f}`")
    if px.oanda_vs_tv_pips is not None:
        price_lines.append(f"- OANDA vs TradingView: `{px.oanda_vs_tv_pips:+.1f}` pips")
    price_lines.append(f"- Verdict: **{px.verdict}**")
    for note in px.notes:
        price_lines.append(f"- {note}")

    macro_lines = []
    for item in intel.macro:
        if item.last is None:
            macro_lines.append(f"- {item.name}: unavailable. {item.note}")
            continue
        chg = f"{item.change_pct:+.2f}%" if item.change_pct is not None else "n/a"
        macro_lines.append(f"- **{item.name}** `{item.last:.3f}` ({chg}). {item.note}")
    if not macro_lines:
        macro_lines.append("- Macro tape not fetched this cycle.")

    driver_lines = [f"- {d}" for d in intel.drivers] or ["- No scheduled driver identified."]
    headline_lines = [
        f"- {h.get('title')} ({h.get('source') or 'news'})" for h in intel.headlines[:8]
    ] or ["- No headlines this cycle."]

    rule_lines = [
        (
            f"- Only EUR/USD. Up to {settings.max_open_positions} desk tickets "
            f"(max {settings.max_same_side_positions} same-side) when the tape is worth it. "
            f"Base risk {settings.risk_per_trade_pct:.0%} of NAV; conviction {settings.conviction_risk_pct:.1%} "
            f"on a high-strength H1-aligned setup; add-on {settings.addon_risk_pct:.2%} only onto a winner; "
            f"fade {settings.fade_risk_pct:.1%} against the tape. Combined open risk cap {settings.max_open_risk_pct:.1%}."
        ),
        "- Tokyo through New York weekdays (00:00–22:00 UTC). No Sunday reopen. Friday flat after 20:00 UTC. Monday Tokyo first 45 minutes sit out.",
        (
            f"- After a stop, wait {settings.post_loss_cooldown_minutes} minutes. "
            f"After a win, wait {settings.reentry_cooldown_minutes} minutes."
        ),
        "- Two consecutive EUR/USD losses sit out until the next session open.",
        "- Last two stops on a side sit that side out even if an earlier outlier win left net P/L green.",
        "- Fade the M5 rip: sell an RSI≥60 / upper-band spike when H1 is not bullish; buy an RSI≤40 / lower-band washout when H1 is not bearish. Never chase the spike or short the bounce.",
        "- After a losing day, cut size; a $250-equivalent desk loss stops new tickets until the next UTC day.",
        "- High-impact EUR or USD prints: stand aside ±30 minutes.",
        "- If OANDA and CurrencyFreaks disagree beyond the warn threshold, do not open a new ticket — unless CF is a stale daily print and live prints (TE / TV / M5) back OANDA.",
        "- Never close, scale, or net against an operator/demo fill (OPEN_ONLY). Journal it and learn. Desk tickets can sit beside it.",
        "- Only take TP1 on desk tickets that are actually in profit, with at least two units and a real target.",
        "- Trade H1-aligned Ox scalp triad (LWMA + envelopes + DSS) or a band/RSI/stoch/CCI extreme — not a mid-range grind against H1.",
        "- Mark the OANDA tape every cycle: indicators, text, trend lines, Fibonacci/zones/channel, swing icons, and candle patterns.",
        "- Extra datasets in `extra datasets/` are studied into `desk/HISTORY.md` as unvalidated research.",
        (
            "- Trading Economics [euro-area/currency](https://tradingeconomics.com/euro-area/currency) "
            "is a third EUR/USD print plus EA/US inflation, Fed/ECB rates, EUR crosses, and TE euro news. "
            "Use it as context. Do not buy a TE 1.16/1.18 recovery forecast against a live H1 downtrend."
        ),
        (
            "- FXStreet [EUR/USD](https://www.fxstreet.com/currencies/eurusd) is daily TA + fundamental wrap "
            "(100-day SMA, Bollinger, RSI, FedWatch, claims, DXY, oil, crowd poll). "
            "A bearish daily with RSI near 32 is not a license to short the washout."
        ),
        (
            "- Barchart [^EURUSD](https://www.barchart.com/forex/quotes/%5EEURUSD) is the fifth print plus "
            "daily S1–S3 (the supports FXStreet omits), 52-week fibs, COT spec crowding, and a 72% Strong Sell opinion. "
            "Specs already net short + RSI oversold at the day low is crowded — do not chase it. Fade rips into R1."
        ),
        (
            "- Investing.com [EUR/USD](https://www.investing.com/currencies/eur-usd) is the sixth print plus "
            "multi-timeframe technicals (30m–monthly), CME euro futures, the pair-page calendar "
            "(claims, EA CPI, CFTC EUR), and euro/dollar news. Daily+weekly Strong Sell is the same crowded-sell "
            "tape — do not chase the day low. CME ~1.1520 is a fade into R1, not a breakout buy."
        ),
        (
            "- TradingView [EURUSD hub](https://www.tradingview.com/symbols/EURUSD/) is the seventh print "
            "(last, TV ratings, performance, volatility, community levels). Sell today + 1W Sell with 1M Neutral "
            "is not a new downtrend. Crowd BUY at 1.1480 is the washout trap — not a ticket."
        ),
        (
            "- Forex Factory [EUR/USD market](https://www.forexfactory.com/market/eurusd) is the pair news "
            "reference (wires + the same-week calendar that already feeds the blackout). "
            "A FF headline is not a ticket. Stand aside ±30 minutes on red EUR or USD prints."
        ),
        (
            "- TradingView [community scripts](https://www.tradingview.com/scripts/) are hunt memory. "
            "Supertrend, TTM squeeze, session VWAP, Donchian sweeps, "
            "Ichimoku, WaveTrend, TMA, and EWMAC run on live OANDA bars. Do not chase a stretch "
            "from VWAP/TMA; do not short a WaveTrend/RSI washout; wait for squeeze fire."
        ),
        "- Operate as an **intraday EUR/USD scalper**, not a multi-day swing and not a multi-month position trader.",
        "- Number one rule: preserve capital. No 100% system. Do not risk more than the sized 0.6–0.9% ticket.",
        "- Sync timeframes: D1 map, H1 direction, M5 trigger. Do not take an H1 long off an M5 sell.",
        "- Trend first; pullbacks in the trend are the entry. Range fades are rips into R1/VWAP, never the washout short.",
        "- Breakouts need a close that holds. A Donchian wick-through that closes back inside is a sweep, not a chase.",
        "- Price action and Fibonacci confirm with H1 — they do not lead. Never walk a stop out of hope.",
        "- Expectancy over win rate. A 40% book with 1:2 R:R pays; a fat-winner mean does not license more sells.",
        "- Journal every fill and close. After a stop or a fat win, sit on hands through the cooldown. Weekend: read D1, wait.",
    ]
    rule_lines.extend(f"- {r}" for r in extra_rules)
    for lesson in lessons[:8]:
        action = lesson.get("action") or "observe"
        fp = lesson.get("fingerprint") or ""
        body = (lesson.get("lesson") or "").split("\n")[0]
        until = lesson.get("skip_until") or ""
        extra = f" until {until}" if until else ""
        if action == "prefer":
            rule_lines.append(f"- Keep taking `{fp}`: {body}")
        else:
            rule_lines.append(f"- Learned `{action}` on `{fp}`{extra}: {body}")

    journal_lines = []
    for row in journals[:8]:
        outcome = row.get("outcome") or "open"
        pl = float(row.get("realized_pl") or 0)
        lesson = (row.get("lesson") or row.get("how_to_avoid") or row.get("entry_thesis") or "").split("\n")[0]
        journal_lines.append(
            f"- {row.get('side')} {row.get('symbol')} **{outcome}** ${pl:+.2f} — {lesson}"
        )
    if not journal_lines:
        journal_lines.append("- No closed EUR/USD journal rows yet.")

    open_lines = []
    for trade in open_trades:
        open_lines.append(
            f"- OPEN {trade.get('side')} {trade.get('symbol')} @ {trade.get('fill_price')} "
            f"SL {trade.get('stop_loss')} TP {trade.get('take_profit_2') or trade.get('take_profit_1')}"
        )
    if not open_lines:
        open_lines.append("- Flat. Looking for the next H1-aligned EUR/USD setup.")

    ts = intel.ts.strftime("%Y-%m-%d %H:%M UTC")
    return "\n".join(
        [
            "# EUR/USD specialist playbook",
            "",
            f"_Last updated: {ts}. This file is rewritten by the desk on every intelligence cycle, fill, and recap._",
            "",
            "## Stance",
            "",
            intel.stance,
            "",
            f"H1 bias: **{intel.h1_bias}**. D1 bias: **{intel.d1_bias}**. Headline sentiment: **{intel.sentiment_label}** ({intel.sentiment:+d}).",
            "",
            "## Open book",
            "",
            *open_lines,
            "",
            "## Price integrity",
            "",
            *price_lines,
            "",
            "## Macro tape (things that move EUR/USD)",
            "",
            *macro_lines,
            "",
            "## Trading Economics (euro-area currency)",
            "",
            *_te_lines(intel),
            "",
            "## FXStreet (EUR/USD forecast and news)",
            "",
            *_fxs_lines(intel),
            "",
            "## Barchart (^EURUSD)",
            "",
            *_bc_lines(intel),
            "",
            "## Investing.com (EUR/USD)",
            "",
            *_inv_lines(intel),
            "",
            "## Forex Factory (EUR/USD market news)",
            "",
            *_ff_lines(intel),
            "",
            "## TradingView (EURUSD hub)",
            "",
            *_tvq_lines(intel),
            "",
            "## TradingView (scripts)",
            "",
            *_tv_lines(intel),
            "",
            "## What can move EUR/USD next",
            "",
            *driver_lines,
            "",
            "## Headlines in the book",
            "",
            *headline_lines,
            "",
            "## How this desk operates",
            "",
            "- Full doctrine: `desk/OPERATING.md` (Ox scalp, LiteFinance, Dukascopy capital-first, Investopedia 8 tips).",
            "- Mistake book: `desk/MISTAKES.md` — overtrading, weekend gap, Monday open, anti-martingale, slippage, stale quotes.",
            "- Google Sheets book: `desk/SHEETS.md` — trades, journals, daily P/L, lessons, account, signals, open tickets.",
            "- News patterns: `desk/NEWS.md` + `desk/NEWS_PATTERNS.md` — 05:00 UTC harvest, later tape check, categories.",
            "- Style: **intraday EUR/USD scalp** — Ox LWMA + envelopes + DSS, short SL/TP, 90-minute time stop. Not a multi-day swing.",
            "- Number one rule: preserve capital. No 100% system. Sync D1 → H1 → M5. Trend first; fade rips, never the washout.",
            "- Breakouts need a close that holds. Journal every fill. Expectancy over win rate. Weekend: read D1 and wait.",
            "",
            "## Standing rules",
            "",
            *rule_lines,
            "",
            "## Recent lessons",
            "",
            *journal_lines,
            "",
            "## How this file is used",
            "",
            "- The bot rereads this playbook before it writes the next intel note and Slack #forex update.",
            "- Losses append to `desk/LEARNING_LOG.md` and refresh the standing rules above.",
            "- Historical files in `extra datasets/` rewrite `desk/HISTORY.md`; exploratory results do not authorize live preferences.",
            "- Trading Economics euro-area/currency is fetched every intel cycle; standing notes live in `desk/TRADINGECONOMICS.md`.",
            "- FXStreet EUR/USD is fetched every intel cycle; standing notes live in `desk/FXSTREET.md`.",
            "- Barchart ^EURUSD is fetched every intel cycle; standing notes live in `desk/BARCHART.md`.",
            "- Investing.com EUR/USD is fetched every intel cycle; standing notes live in `desk/INVESTING.md`.",
            "- Forex Factory EUR/USD market news is fetched every intel cycle; standing notes live in `desk/FOREXFACTORY.md`.",
            "- Dual venue: OANDA practice is the primary book; MT4 demo copies sit beside it (`desk/MT4.md`). Copies do not eat OANDA stack caps. Operator MT4 tickets stay hands-off.",
            "- TradingView EURUSD hub and community scripts are fetched every intel cycle; standing notes live in `desk/TRADINGVIEW.md`.",
            "- Operating doctrine lives in `desk/OPERATING.md`. Ox scalp recipe lives in `desk/SCALPING.md`. Mistake taxonomy lives in `desk/MISTAKES.md`. Google Sheets workbook notes live in `desk/SHEETS.md`. News harvest + pattern book live in `desk/NEWS.md` and `desk/NEWS_PATTERNS.md`. Reread them.",
            "- Do not delete this file; rewrite it. Growth is the point.",
            "",
        ]
    )


def write_playbook(markdown: str) -> Path:
    ensure_desk_dir()
    PLAYBOOK_PATH.write_text(markdown if markdown.endswith("\n") else markdown + "\n", encoding="utf-8")
    return PLAYBOOK_PATH


def publish_intel(
    intel: IntelReport,
    *,
    lessons: list[dict[str, Any]] | None = None,
    journals: list[dict[str, Any]] | None = None,
    open_trades: list[dict[str, Any]] | None = None,
    extra_rules: list[str] | None = None,
    log_title: str = "Intel cycle",
) -> Path:
    markdown = render_playbook(
        intel=intel,
        lessons=lessons,
        journals=journals,
        open_trades=open_trades,
        extra_rules=extra_rules,
    )
    path = write_playbook(markdown)
    bullets = [intel.stance, *intel.price.notes[:3], *intel.drivers[:3]]
    append_learning(log_title, bullets, ts=intel.ts)
    return path
