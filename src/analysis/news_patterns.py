"""Classify EUR/USD headlines, log them, and score whether they moved the tape.

The 05:00 UTC scan (and every intel harvest) stores a predicted EUR/USD
direction. Later M5 closes are compared so the desk can keep a hit-rate
by category instead of treating every headline as a ticket.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data.news import Headline, score_sentiment
from src.data.storage import Bar, NewsItem, session_scope
from src.utils import pip_size, utcnow

ROOT = Path(__file__).resolve().parents[2]
DESK_DIR = ROOT / "desk"
PATTERNS_PATH = DESK_DIR / "NEWS_PATTERNS.md"
LOG_PATH = DESK_DIR / "NEWS_LOG.md"
MAX_LOG_CHARS = 160_000

# (category, keywords, textbook reaction). First match wins.
CATEGORY_RULES: list[tuple[str, tuple[str, ...], str]] = [
    (
        "inflation",
        ("cpi", "consumer price", "inflation", "pce", "core pce", "hicp"),
        "Inflation prints: hotter than forecast usually bids USD (EUR/USD down); cooler prints can lift EUR/USD.",
    ),
    (
        "labor",
        ("nfp", "non-farm", "nonfarm", "payroll", "jobless", "claims", "unemployment"),
        "Payrolls: a strong beat typically bids USD; a miss can squeeze USD shorts and lift EUR/USD.",
    ),
    (
        "fed",
        ("fomc", "fed funds", "interest rate decision", "powell", "federal reserve", "hawkish fed", "dovish fed", "beige book", "warsh"),
        "Fed: hawkish hold / higher-for-longer bids USD; a dovish cut or ease-later signal lifts EUR/USD.",
    ),
    (
        "ecb",
        ("ecb", "lagarde", "refinancing", "deposit facility", "makhlouf", "rehn", "kazaks", "kazaeks", "nagel", "schnabel"),
        "ECB: hawkish language supports EUR; a dovish cut or QT slowdown weighs on EUR/USD.",
    ),
    (
        "pmi",
        ("ism", "pmi", "ifo", "zew"),
        "PMI/ISM: U.S. strength bids USD; Eurozone strength (Germany IFO/ZEW) supports EUR.",
    ),
    (
        "growth",
        ("gdp", "growth"),
        "GDP: stronger U.S. growth bids USD; stronger Eurozone growth supports EUR.",
    ),
    (
        "ppi",
        ("ppi", "producer price"),
        "PPI often leads CPI. Hot U.S. PPI is USD-positive until the next CPI confirms.",
    ),
    (
        "retail",
        ("retail sales", "retail"),
        "Retail sales: a U.S. beat supports USD; a Eurozone beat supports EUR.",
    ),
    (
        "yields",
        ("yield", "treasury", "10y", "10-year", "bund"),
        "Rising U.S. yields typically bid USD and press EUR/USD; a yield retreat can lift the pair.",
    ),
    (
        "energy",
        ("brent", "crude", "oil price", "wti", "pipeline"),
        "Energy: a jump in oil can lift Eurozone inflation and complicate the ECB; USD often catches a bid on the first shock.",
    ),
    (
        "dollar",
        ("dxy", "dollar index", "greenback", "us dollar"),
        "A firmer dollar index usually weighs on EUR/USD; dollar softness is the opposite.",
    ),
    (
        "risk",
        ("vix", "risk-off", "risk off", "risk-on", "risk on", "geopolit", "war ", "tariff"),
        "Risk-off often bids USD. Risk-on can support EUR/USD if yields are not ripping.",
    ),
    (
        "commentary",
        ("forecast", "price forecast", "sma", "break below", "break above", "target", "technical"),
        "Desk commentary, not a print. Use it as context. The H1 reaction still decides the ticket.",
    ),
]

HORIZONS = (
    ("30m", timedelta(minutes=30)),
    ("1h", timedelta(hours=1)),
    ("4h", timedelta(hours=4)),
)
PRIMARY = "1h"
MOVE_PIPS = 5.0  # below this the tape did not really answer the headline


@dataclass(slots=True)
class NewsClass:
    category: str
    predicted: str
    reason: str
    reaction: str
    sentiment: int


def fingerprint_title(title: str) -> str:
    text = re.sub(r"https?://\S+", "", title or "")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text[:240]


def classify_headline(title: str) -> NewsClass:
    blob = (title or "").lower()
    category = "other"
    reaction = (
        "Can move EUR/USD through USD or EUR rates. Stand aside through the print, "
        "then trade the H1 reaction rather than the first tick."
    )
    for name, keys, text in CATEGORY_RULES:
        if any(key in blob for key in keys):
            category = name
            reaction = text
            break
    sentiment = score_sentiment(title or "")
    if sentiment >= 1:
        predicted = "bullish"
    elif sentiment <= -1:
        predicted = "bearish"
    else:
        predicted = "mixed"
    if category == "commentary" and predicted != "mixed":
        reason = f"{reaction} Headline keywords lean {predicted}."
    elif predicted == "mixed":
        reason = reaction
    else:
        reason = f"{reaction} Headline keywords lean {predicted} EUR/USD."
    return NewsClass(
        category=category,
        predicted=predicted,
        reason=reason,
        reaction=reaction,
        sentiment=sentiment,
    )


def _mid_at_or_after(session: Session, when: datetime) -> float | None:
    stmt = (
        select(Bar)
        .where(Bar.symbol == "EUR/USD", Bar.timeframe == "M5", Bar.ts >= when)
        .order_by(Bar.ts.asc())
        .limit(1)
    )
    row = session.scalar(stmt)
    if row is not None:
        return float(row.close)
    stmt = (
        select(Bar)
        .where(Bar.symbol == "EUR/USD", Bar.timeframe == "M5", Bar.ts <= when)
        .order_by(Bar.ts.desc())
        .limit(1)
    )
    row = session.scalar(stmt)
    return float(row.close) if row is not None else None


def _verdict(predicted: str, move_pips: float | None) -> str:
    if move_pips is None:
        return "pending"
    if abs(move_pips) < MOVE_PIPS:
        return "unclear"
    went_up = move_pips >= MOVE_PIPS
    if predicted == "bullish":
        return "correct" if went_up else "wrong"
    if predicted == "bearish":
        return "correct" if not went_up else "wrong"
    return "unclear"


def ingest_headlines(
    session: Session,
    headlines: Iterable[Headline],
    *,
    price: float | None,
    scan_kind: str = "harvest",
    now: datetime | None = None,
) -> int:
    """Insert unseen EUR/USD headlines. Returns how many were new."""
    now = now or utcnow()
    added = 0
    existing = {
        row[0]
        for row in session.execute(select(NewsItem.fingerprint)).all()
        if row[0]
    }
    for item in headlines:
        title = (item.title or "").strip()
        if not title:
            continue
        fp = fingerprint_title(title)
        if not fp or fp in existing:
            continue
        tagged = classify_headline(title)
        row = NewsItem(
            ts=now,
            published=item.published,
            source=item.source or "unknown",
            title=title[:500],
            url=(item.url or "")[:500],
            fingerprint=fp,
            category=tagged.category,
            predicted=tagged.predicted,
            predicted_reason=tagged.reason[:800],
            sentiment=tagged.sentiment,
            price_at=price,
            scan_kind=scan_kind,
            verdict="pending",
        )
        session.add(row)
        existing.add(fp)
        added += 1
    if added:
        session.flush()
    return added


def review_news_outcomes(session: Session, *, now: datetime | None = None) -> int:
    """Fill 30m/1h/4h prices and mark correct/wrong/unclear."""
    now = now or utcnow()
    pending = list(
        session.scalars(
            select(NewsItem).where(NewsItem.verdict == "pending").order_by(NewsItem.ts.asc()).limit(400)
        )
    )
    updated = 0
    for row in pending:
        start = row.ts
        if start is None:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if row.price_at is None:
            row.price_at = _mid_at_or_after(session, start)
        changed = False
        for name, delta in HORIZONS:
            due = start + delta
            if now < due:
                continue
            attr = f"price_{name}"
            if getattr(row, attr) is None:
                later = _mid_at_or_after(session, due)
                if later is not None:
                    setattr(row, attr, later)
                    if row.price_at is not None:
                        move = round((later - float(row.price_at)) / pip_size("EUR/USD"), 1)
                        setattr(row, f"move_{name}_pips", move)
                    changed = True
        primary_move = row.move_1h_pips
        if primary_move is None and now >= start + timedelta(hours=1):
            # 1h bar missing; fall back to whatever we have.
            primary_move = row.move_30m_pips if row.move_4h_pips is None else row.move_4h_pips
        if primary_move is not None or (row.price_1h is not None and row.price_at is not None):
            if primary_move is None and row.price_1h is not None and row.price_at is not None:
                primary_move = round((float(row.price_1h) - float(row.price_at)) / pip_size("EUR/USD"), 1)
                row.move_1h_pips = primary_move
            row.verdict = _verdict(row.predicted, primary_move)
            row.reviewed_at = now
            changed = True
        if changed:
            updated += 1
    if updated:
        session.flush()
    return updated


def pattern_rows(session: Session) -> list[dict[str, Any]]:
    rows = list(session.scalars(select(NewsItem)))
    buckets: dict[str, dict[str, Any]] = {}
    for item in rows:
        bucket = buckets.setdefault(
            item.category,
            {
                "category": item.category,
                "samples": 0,
                "pending": 0,
                "correct": 0,
                "wrong": 0,
                "unclear": 0,
                "moves": [],
                "last_title": item.title,
                "reaction": classify_headline(item.title).reaction,
            },
        )
        bucket["samples"] += 1
        bucket["last_title"] = item.title
        verdict = item.verdict or "pending"
        bucket[verdict] = bucket.get(verdict, 0) + 1
        if item.move_1h_pips is not None:
            bucket["moves"].append(float(item.move_1h_pips))
    out = []
    for bucket in buckets.values():
        scored = bucket["correct"] + bucket["wrong"]
        hit = (bucket["correct"] / scored) if scored else None
        moves = bucket["moves"]
        avg = sum(abs(m) for m in moves) / len(moves) if moves else None
        out.append(
            {
                "category": bucket["category"],
                "samples": bucket["samples"],
                "pending": bucket.get("pending", 0),
                "correct": bucket["correct"],
                "wrong": bucket["wrong"],
                "unclear": bucket["unclear"],
                "hit_rate": None if hit is None else round(hit, 3),
                "avg_abs_1h_pips": None if avg is None else round(avg, 1),
                "reaction": bucket["reaction"],
                "last_title": bucket["last_title"],
            }
        )
    out.sort(key=lambda r: (-(r["samples"] or 0), r["category"]))
    return out


def render_patterns(rows: list[dict[str, Any]], *, now: datetime | None = None) -> str:
    now = now or utcnow()
    lines = [
        "# EUR/USD news patterns",
        "",
        f"_Rewritten {now.strftime('%Y-%m-%d %H:%M UTC')} from logged headlines vs later M5 closes. "
        "A category needs several scored prints before the desk trusts it. Commentary is context, not a ticket._",
        "",
        "| Category | Samples | Correct | Wrong | Unclear | Pending | 1h hit rate | Avg |abs| 1h |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    if not rows:
        lines.append("| _(none yet)_ | 0 | 0 | 0 | 0 | 0 | — | — |")
    for row in rows:
        hit = "—" if row["hit_rate"] is None else f"{100 * row['hit_rate']:.0f}%"
        avg = "—" if row["avg_abs_1h_pips"] is None else f"{row['avg_abs_1h_pips']:.1f}"
        lines.append(
            f"| {row['category']} | {row['samples']} | {row['correct']} | {row['wrong']} | "
            f"{row['unclear']} | {row['pending']} | {hit} | {avg} |"
        )
    lines += [
        "",
        "## How to read a category",
        "",
    ]
    seen = set()
    for row in rows:
        if row["category"] in seen:
            continue
        seen.add(row["category"])
        lines.append(f"- **{row['category']}** — {row['reaction']}")
    if not rows:
        for name, _keys, text in CATEGORY_RULES:
            lines.append(f"- **{name}** — {text}")
        lines.append("- **other** — Unclassified EUR/USD wire. Wait for H1.")
    lines += [
        "",
        "## Standing rules",
        "",
        "- Harvest is EUR/USD only (Forex Factory market/eurusd, NewsNow EUR/USD page, Google News EURUSD, Yahoo/ECB/Fed, intel hubs).",
        "- A headline is **not** a ticket. Ox scalp + H1 still fire the order.",
        "- Revisit uses the **1-hour** M5 close vs the mid at capture. Under 5 pips is unclear, not a win.",
        "- Commentary/forecast headlines are logged so the desk can see they do not lead the tape.",
        "- 05:00 UTC is the dedicated morning scan; intel restocks the log as stories land.",
        "",
    ]
    return "\n".join(lines) + "\n"


def append_news_log(title: str, bullets: Iterable[str], *, ts: datetime | None = None) -> None:
    DESK_DIR.mkdir(parents=True, exist_ok=True)
    ts = ts or utcnow()
    lines = [f"## {ts.strftime('%Y-%m-%d %H:%M UTC')} — {title}"]
    for item in bullets:
        text = str(item).strip()
        if text:
            lines.append(f"- {text}")
    lines.append("")
    existing = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else (
        "# EUR/USD news log\n\nDated harvest notes. The desk appends after the 05:00 UTC scan and after intel restocks.\n\n"
    )
    blob = existing.rstrip() + "\n\n" + "\n".join(lines)
    if len(blob) > MAX_LOG_CHARS:
        marker = "\n## "
        idx = blob.find(marker, len(blob) - MAX_LOG_CHARS)
        blob = "# EUR/USD news log\n\n_Older entries were trimmed._\n" + blob[idx:]
    LOG_PATH.write_text(blob, encoding="utf-8")


def write_patterns(session: Session, *, now: datetime | None = None) -> list[dict[str, Any]]:
    rows = pattern_rows(session)
    DESK_DIR.mkdir(parents=True, exist_ok=True)
    PATTERNS_PATH.write_text(render_patterns(rows, now=now), encoding="utf-8")
    return rows


def harvest_and_score(
    headlines: list[Headline],
    *,
    price: float | None,
    scan_kind: str = "harvest",
    session: Session | None = None,
) -> dict[str, Any]:
    """Ingest, revisit due items, rewrite NEWS_PATTERNS.md. Safe to call off-clock."""

    def _run(sess: Session) -> dict[str, Any]:
        added = ingest_headlines(sess, headlines, price=price, scan_kind=scan_kind)
        reviewed = review_news_outcomes(sess)
        patterns = write_patterns(sess)
        from sqlalchemy import func

        stored = int(sess.scalar(select(func.count()).select_from(NewsItem)) or 0)
        pending = int(
            sess.scalar(select(func.count()).select_from(NewsItem).where(NewsItem.verdict == "pending")) or 0
        )
        return {
            "ok": True,
            "added": added,
            "reviewed": reviewed,
            "stored": stored,
            "pending": pending,
            "patterns": patterns,
        }

    if session is not None:
        return _run(session)
    with session_scope() as sess:
        return _run(sess)


def recent_news(session: Session, limit: int = 40) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(select(NewsItem).order_by(NewsItem.ts.desc(), NewsItem.id.desc()).limit(limit))
    )
    return [serialize_news_item(row) for row in rows]


def serialize_news_item(row: NewsItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "ts": row.ts.isoformat() if row.ts else None,
        "published": row.published.isoformat() if row.published else None,
        "source": row.source,
        "title": row.title,
        "url": row.url,
        "category": row.category,
        "predicted": row.predicted,
        "predicted_reason": row.predicted_reason,
        "sentiment": row.sentiment,
        "price_at": row.price_at,
        "price_30m": row.price_30m,
        "price_1h": row.price_1h,
        "price_4h": row.price_4h,
        "move_30m_pips": row.move_30m_pips,
        "move_1h_pips": row.move_1h_pips,
        "move_4h_pips": row.move_4h_pips,
        "verdict": row.verdict,
        "scan_kind": row.scan_kind,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
    }
