"""Minute-by-minute orchestration: Fetch → Analyze → Execute → Notify."""

from __future__ import annotations

import threading
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from src.analysis.indicators import compute_indicators
from src.analysis.reflection import (
    backfill_missing_journals,
    build_tape_reflection,
    daily_lesson_digest,
    estimate_realized_pl,
    fingerprint_from_signal,
    infer_close_reason,
    restudy_learned_rules,
    lesson_gate,
    record_entry,
    record_exit,
)
from src import __version__
from src.analysis.charting import build_chart_pack, oanda_thesis_comment, oanda_trade_comment
from src.analysis.markup import latest_setup_label
from src.analysis.desk import build_morning_brief, build_night_recap, upsert_desk_note
from src.analysis.intel import (
    IntelReport,
    build_intel_report,
    check_price_consistency,
    fetch_macro_tape,
)
from src.analysis.playbook import PLAYBOOK_PATH, append_learning, publish_intel, read_learning_log, read_playbook
from src.data.tradingeconomics import fetch_eurusd_snapshot
from src.data.fxstreet import fetch_eurusd_snapshot as fetch_fxstreet_snapshot
from src.data.barchart import fetch_eurusd_snapshot as fetch_barchart_snapshot
from src.data.investing import fetch_eurusd_snapshot as fetch_investing_snapshot
from src.data.tradingview import (
    fetch_scripts_snapshot as fetch_tradingview_snapshot,
    fetch_eurusd_quote as fetch_tradingview_quote,
)
from src.data.forexfactory import fetch_eurusd_snapshot as fetch_forexfactory_snapshot
from src.analysis.growth import (
    GrowthReport,
    growth_gate,
    study_book,
    widen_to_min_stop,
    write_growth,
)
from src.analysis.mistakes import live_mistake_gate, calendar_hold_reason, broker_market_hours
from src.analysis.signals import TradeSignal, bars_to_frame, evaluate_signal
from src.config import Settings, Timeframe, get_settings
from src.data.fetcher import MarketDataFetcher, Quote
from src.data.datasets import HistoryReport, study_extra_datasets, write_history
from src.data.news import NewsDesk
from src.data.storage import (
    AccountSnapshot,
    PipelineRun,
    Trade,
    get_desk_note,
    get_open_trades,
    get_or_create_daily_pnl,
    get_recent_desk_notes,
    get_recent_journals,
    get_recent_tape_notes,
    get_active_learned_rules,
    insert_tape_note,
    init_db,
    insert_signal,
    insert_trade,
    latest_pipeline_run,
    load_bars,
    peak_nav,
    purge_mislabelled_history_signals,
    session_scope,
    upsert_bars,
    upsert_indicators,
    get_mt4_sibling,
)
from src.execution.paper_broker import PaperBroker
from src.execution.mt4 import MT4Broker, VENUE as VENUE_MT4
from src.execution.risk_manager import AccountState, RiskManager, same_side_tickets
from src.execution.trade_guard import (
    SOURCE_BOT,
    SOURCE_HUMAN,
    adopted_levels,
    classify_remote_trade,
    mark_price,
    operator_open_on_symbol,
    partial_close_units,
    should_flatten_scalp,
    should_take_partial,
)
from src.notifications.slack_bot import SlackNotifier
from src.notifications.sheets import SheetsPublisher, publish_from_db
from src.utils import canonical_pair, price_to_pips, to_display_symbol, utcnow

ALL_TIMEFRAMES: tuple[Timeframe, ...] = ("M1", "M5", "H1", "D1")

_STICKY_SKIP_MARKERS = (
    "underwater ticket",
    "anti-martingale",
    "averaging down",
    "max same-side desk",
    "max open desk positions",
    "scalp spread",
    "daily loss limit",
    "soft halt",
    "max drawdown",
    "trading paused from dashboard",
    "fifo",
    "will not stack another",
    "overtrading halt",
    "kill switch",
    "stale",
    "cost:",
    "slippage cool-off",
    "weekend gap",
    "session-open",
)


def is_sticky_skip(reason: str | None) -> bool:
    """True when the same block will fire every M5 until the book changes."""
    text = (reason or "").lower()
    return any(marker in text for marker in _STICKY_SKIP_MARKERS)


class TradingPipeline:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.fetcher = MarketDataFetcher(self.settings)
        self.broker = PaperBroker(self.settings, client=self.fetcher.oanda)
        self.mt4 = MT4Broker(self.settings)
        self.risk = RiskManager(self.settings)
        self.slack = SlackNotifier(self.settings)
        self.sheets = SheetsPublisher(self.settings)
        self.news = NewsDesk()
        self._lock = threading.RLock()
        self._quotes: dict[str, Quote] = {}
        self._last_cycle: dict[str, Any] = {}
        self._account: AccountState | None = None
        self._warm = False
        self.startup_tasks = {"state": "pending", "current": None, "completed": [], "failed": []}
        self.trading_enabled = False  # Explicitly arm each process after reviewing the account.
        self._last_tape_slack: datetime | None = None
        self._last_tape_key: str | None = None
        self._last_tape_write: datetime | None = None
        self._intel: IntelReport | None = None
        self._last_intel_at: datetime | None = None
        self._remote_open: list[dict[str, Any]] = []
        self._growth: GrowthReport | None = None
        self._history: HistoryReport | None = None
        self._last_growth_focus: str | None = None
        self._last_history_focus: str | None = None
        self._history_studying = False
        self._history_thread: threading.Thread | None = None
        self._history_lock = threading.Lock()
        self._fifo_block: dict[str, str] = {}
        self._sheets_lock = threading.Lock()
        self._sheets_thread: threading.Thread | None = None

    def startup(self) -> None:
        init_db()
        from src.analysis.ownership_audit import reconcile_legacy_closed_ownership
        with session_scope() as session:
            ownership = reconcile_legacy_closed_ownership(session, self.broker)
            logger.info("Legacy closed-trade ownership audit: {}", ownership)
        logger.info("Config: {}", self.settings.masked_summary())
        try:
            account = self.broker.account_summary()
            self._account = account
            logger.info(
                "OANDA {} account {}  NAV=${:,.2f}  balance=${:,.2f}",
                self.settings.oanda_environment,
                self.broker.account_id,
                account.nav,
                account.balance,
            )
            self._persist_snapshot(account)
        except Exception as exc:
            logger.error("Unable to reach OANDA on startup: {}", exc)
        try:
            mt4_status = self.mt4.status()
            logger.info(
                "MT4 venue {} login={} server={} mode={}",
                "on" if mt4_status.enabled else "off",
                mt4_status.login or "(none)",
                mt4_status.server or "(none)",
                mt4_status.mode,
            )
        except Exception as exc:
            logger.warning("MT4 status on startup failed: {}", exc)
        try:
            self.fetcher.ensure_reference_mids(self.settings.symbols, force=True)
        except Exception as exc:
            logger.warning("CurrencyFreaks unavailable on startup: {}", exc)
        try:
            ok, detail = self.slack.ensure_channel()
            if ok:
                self.slack.startup_ping()
                logger.info("Slack posting to {}", detail)
            else:
                logger.warning("Slack is not live: {}", detail)
        except Exception as exc:
            logger.warning("Slack startup failed: {}", exc)
        self._flatten_off_watchlist()
        self._backfill()
        try:
            with session_scope() as session:
                n = purge_mislabelled_history_signals(session)
                if n:
                    logger.info("Removed {} replay rows that were stored as live signals", n)
        except Exception:
            logger.exception("Could not purge mislabelled history signals")
        try:
            quotes = {q.symbol: q for q in self.fetcher.fetch_quotes(self.settings.symbols)}
            self._quotes = quotes
        except Exception as exc:
            logger.warning("Startup quotes unavailable: {}", exc)
        with session_scope() as session:
            n = backfill_missing_journals(session, quotes=self._quotes, settings=self.settings)
            if n:
                logger.info("Backfilled {} trade-journal rows", n)
        try:
            self.refresh_growth()
        except Exception:
            logger.exception("Startup growth study failed")
        self._warm = True
        logger.info("Core startup complete — scheduler and dashboard can start")

    def run_startup_tasks(self) -> None:
        """Optional enrichment must not delay dashboard availability."""
        tasks = (
            ("initial_scan", lambda: self.run_cycle(("M1", "M5", "H1", "D1"))),
            ("desk_notes", self._maybe_catchup_desk_notes),
            ("sheets", self.kick_sheets_sync),
            ("tape", self.send_tape_pulse),
            ("intel", lambda: self.run_intel(force_slack=True)),
            ("history", self.kick_history_study),
        )
        self.startup_tasks = {"state": "running", "current": None, "completed": [], "failed": []}
        for name, action in tasks:
            self.startup_tasks = {**self.startup_tasks, "current": name}
            try:
                result = action()
                if isinstance(result, dict) and (result.get("status") == "error" or result.get("ok") is False):
                    raise RuntimeError("Task reported failure")
            except Exception:
                self.startup_tasks = {**self.startup_tasks, "failed": [*self.startup_tasks["failed"], name]}
                logger.exception("Startup task {} failed; continuing remaining tasks", name)
            else:
                self.startup_tasks = {**self.startup_tasks, "completed": [*self.startup_tasks["completed"], name]}
        self.startup_tasks = {**self.startup_tasks, "current": None,
                              "state": "degraded" if self.startup_tasks["failed"] else "complete"}

    def refresh_documentation(self):
        from src.analysis.documentation import export_documents
        try:
            with session_scope() as session:
                self.documentation_status = export_documents(session)
        except Exception as exc:
            self.documentation_status = {"ok": False, "error_type": type(exc).__name__}
            logger.exception("Documentation export failed; retrying on next scheduled refresh")
        return self.documentation_status

    def shutdown(self) -> None:
        self.fetcher.close()

    def _backfill(self) -> None:
        counts = {"M1": 400, "M5": 300, "H1": 250, "D1": 180}
        for symbol in self.settings.symbols:
            for tf, count in counts.items():
                try:
                    candles = self.fetcher.fetch_candles(symbol, tf, count=count)
                    with session_scope() as session:
                        upsert_bars(session, [c.to_row() for c in candles])
                    logger.info("Backfilled {} {} ({} bars)", symbol, tf, len(candles))
                except Exception as exc:
                    logger.exception("Backfill failed {} {}: {}", symbol, tf, exc)

    def run_cycle(self, timeframes: tuple[Timeframe, ...] | None = None) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            logger.warning("Skipping cycle — previous still running")
            return {"status": "skipped"}
        try:
            return self._run_cycle_locked(timeframes or ("M1", "M5"))
        finally:
            self._lock.release()

    def _run_cycle_locked(self, timeframes: tuple[Timeframe, ...]) -> dict[str, Any]:
        started = utcnow()
        summary: dict[str, Any] = {
            "started_at": started.isoformat(),
            "status": "ok",
            "symbols": [],
            "orders_placed": 0,
            "signals": 0,
        }
        with session_scope() as session:
            run = PipelineRun(started_at=started, status="running")
            session.add(run)
            session.flush()
            run_id = run.id
        try:
            quotes = {q.symbol: q for q in self.fetcher.fetch_quotes(self.settings.symbols)}
            self._quotes = quotes
            account = self.broker.account_summary()
            self._account = account
            self._persist_snapshot(account)
            self._flatten_off_watchlist()
            self._sync_open_trades(account)

            for symbol in self.settings.symbols:
                symbol_result = self._process_symbol(symbol, timeframes, quotes.get(symbol), account)
                summary["symbols"].append(symbol_result)
                summary["signals"] += int(symbol_result.get("signal") is not None)
                summary["orders_placed"] += int(bool(symbol_result.get("order_placed")))

            with session_scope() as session:
                run = session.get(PipelineRun, run_id)
                if run:
                    run.finished_at = utcnow()
                    run.status = "ok"
                    run.symbols_processed = len(summary["symbols"])
                    run.signals_emitted = summary["signals"]
                    run.orders_placed = summary["orders_placed"]
        except Exception as exc:
            logger.exception("Pipeline cycle failed")
            summary["status"] = "error"
            summary["error"] = str(exc)
            with session_scope() as session:
                run = session.get(PipelineRun, run_id)
                if run:
                    run.finished_at = utcnow()
                    run.status = "error"
                    run.error = str(exc)
        summary["finished_at"] = utcnow().isoformat()
        self._last_cycle = summary
        return summary

    def _process_symbol(
        self,
        symbol: str,
        timeframes: tuple[Timeframe, ...],
        quote: Quote | None,
        account: AccountState,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"symbol": symbol}
        for tf in timeframes:
            try:
                candles = self.fetcher.fetch_candles(symbol, tf, count=250)
                with session_scope() as session:
                    upsert_bars(session, [c.to_row() for c in candles])
                    self._store_latest_indicators(session, symbol, tf)
            except Exception as exc:
                logger.exception("Fetch/analyze failed {} {}", symbol, tf)
                result["error"] = str(exc)
                return result

        with session_scope() as session:
            signal_rows = load_bars(session, symbol, self.settings.signal_timeframe, limit=300)
            htf_rows = load_bars(session, symbol, self.settings.htf_bias_timeframe, limit=250)
            d1_rows = load_bars(session, symbol, "D1", limit=180)
            frame = bars_to_frame(signal_rows)
            htf = bars_to_frame(htf_rows)
            d1 = bars_to_frame(d1_rows)
            signal = evaluate_signal(
                symbol,
                self.settings.signal_timeframe,
                frame,
                htf_bars=htf,
                d1_bars=d1,
                settings=self.settings,
            )
            result["signal"] = signal.action
            from src.analysis.evidence import decision_context
            signal.decision_context = decision_context(
                settings=self.settings, quote=quote, account=account,
                frames={"signal": frame, "htf": htf, "daily": d1}, captured_at=utcnow(),
            )
            from src.analysis.documentation import read_documentation
            signal.decision_context["documentation"] = read_documentation()
            signal.decision_context["confirmation_review"] = signal.confirmation_review
            result["reason"] = signal.reason
            result["strength"] = signal.strength

            if signal.action == "HOLD":
                insert_signal(session, signal.to_row(skipped=False))
                self._write_tape(session, signal)
                return result

            if signal.action in {"BUY", "SELL"}:
                from src.analysis.entry_confirmation import reentry_reason, latest_bot_close
                last = latest_bot_close(session, symbol)
                prior = None if last is None else {'side': last.side, 'pl': float(last.realized_pl or 0), 'closed_at': last.closed_at}
                blocked = reentry_reason(signal.action, frame, signal.timeframe, prior)
                signal.decision_context['reentry_confirmation'] = {'allowed': blocked is None, 'reason': blocked,
                    'enabled': self.settings.confirmed_entry_policy,
                    'previous_bot_trade_id': last.id if last else None}
                if blocked and self.settings.confirmed_entry_policy:
                    return self._skip_trade(session, signal, result, blocked)

            try:
                self.news.refresh(tavily_key=self.settings.tavily_api_key.get_secret_value())
            except Exception:
                logger.debug("News refresh failed during cycle")
            pause = self.news.blackout_reason(utcnow(), self.settings.news_blackout_minutes)
            signal.decision_context["news_check"] = {
                "checked_at": utcnow().isoformat(), "blackout_reason": pause,
                "coverage_verified": False,
            }
            if pause:
                return self._skip_trade(session, signal, result, pause, extra_slack=True)

            if self._intel and self._intel.price.verdict == "disagree":
                skip = (
                    "Price integrity disagree — OANDA and CurrencyFreaks are too far apart "
                    "for a new EUR/USD ticket"
                )
                return self._skip_trade(session, signal, result, skip, extra_slack=True)

            # Candle/news work can outlive the cycle-start quote. Refresh before entry gates.
            try:
                quote = next((q for q in self.fetcher.fetch_quotes([symbol]) if q.symbol == symbol), None)
            except Exception:
                return self._skip_trade(session, signal, result, "Entry quality: fresh OANDA quote unavailable")
            if not self._management_quote_ready(quote):
                return self._skip_trade(session, signal, result, "Entry quality: fresh tradeable OANDA bid/ask required")
            self._quotes[symbol] = quote
            from src.analysis.entry_quality import entry_quality
            quality = entry_quality(signal, quote, self.settings)
            signal.decision_context["entry_quality"] = quality
            if not quality["allowed"]:
                return self._skip_trade(session, signal, result, quality["reason"])

            mist = live_mistake_gate(
                session=session,
                signal=signal,
                quote=quote,
                intel=self._intel,
                settings=self.settings,
            )
            if not mist.allowed:
                extra = mist.code in {"stale_quote", "overtrading"}
                return self._skip_trade(session, signal, result, mist.reason, extra_slack=extra)

            if (
                getattr(self.settings, "trading_style", "scalp") == "scalp"
                and quote is not None
                and quote.spread is not None
            ):
                spread_pips = price_to_pips(symbol, float(quote.spread))
                cap = float(getattr(self.settings, "scalp_max_spread_pips", 1.8) or 1.8)
                if spread_pips > cap:
                    skip = (
                        f"Scalp spread {spread_pips:.1f} pips is wider than {cap:.1f} — "
                        "wait for London/NY compression."
                    )
                    return self._skip_trade(session, signal, result, skip)

            fifo_key = f"{symbol}|{signal.action}"
            open_now = get_open_trades(session, symbol)
            if not same_side_tickets(open_now, signal.action):
                self._fifo_block.pop(fifo_key, None)
            fifo_reason = self._fifo_block.get(fifo_key)
            if fifo_reason:
                skip = (
                    f"OANDA FIFO will not stack another {signal.action} on {symbol} — "
                    "manage the open fill"
                )
                return self._skip_trade(session, signal, result, skip)

            if operator_open_on_symbol(
                symbol,
                remote_rows=self._remote_open,
                local_open=get_open_trades(session, symbol),
            ):
                logger.info(
                    "Operator {} ticket is live — new desk fills use OPEN_ONLY so they sit beside it",
                    symbol,
                )

            tradeable = True if quote is None else quote.tradeable
            mid = quote.mid if quote else signal.price
            quote_fx = self.broker.quote_to_usd(symbol, mid)
            gate = lesson_gate(
                session,
                fingerprint_from_signal(signal),
                signal.strength,
                signal=signal,
                settings=self.settings,
            )
            if not gate.allowed:
                return self._skip_trade(session, signal, result, gate.reason, extra_slack=True)

            if self._growth is None:
                self.refresh_growth(session=session)
            grown = growth_gate(
                signal,
                self._growth,
                intel=self._intel,
                history=self._history,
                settings=self.settings,
            )
            if not grown.allowed:
                return self._skip_trade(session, signal, result, grown.reason, extra_slack=True)
            signal = widen_to_min_stop(signal, grown.min_stop_pips, self.settings)
            result["growth"] = grown.reason
            result["size_hint"] = grown.action
            signal.decision_context["growth"] = {"action": grown.action, "reason": grown.reason}

            htf_aligned = (
                (signal.action == "BUY" and signal.htf_bias == "bullish")
                or (signal.action == "SELL" and signal.htf_bias == "bearish")
            )
            decision = self.risk.evaluate(
                session=session,
                symbol=symbol,
                side=signal.action,
                entry=quality["worst_entry"],
                notional_price=max(quality["worst_entry"], signal.entry or signal.price, quote.ask),
                stop_loss=signal.stop_loss or signal.price,
                account=account,
                instrument_tradeable=tradeable,
                quote_to_usd=quote_fx,
                mark=mid,
                strength=signal.strength,
                htf_aligned=htf_aligned,
                growth_action=grown.action,
            )
            signal.decision_context["risk"] = {
                "allowed": decision.allowed, "reason": decision.reason,
                "units": decision.units, "size_mode": decision.size_mode,
            }
            if not decision.allowed or not self.trading_enabled:
                skip = decision.reason if not decision.allowed else "Trading paused from dashboard"
                return self._skip_trade(session, signal, result, skip, extra_slack=True)

            if not self._management_quote_ready(quote):
                return self._skip_trade(session, signal, result, "Fresh tradeable OANDA bid/ask required")
            if calendar_hold_reason(utcnow(), settings=self.settings):
                return self._skip_trade(session, signal, result, "Calendar entry window closed")
            from src.execution.order_intent import claim_entry
            candle = frame.index[-1]
            candle_close = candle + timedelta(minutes={"M1": 1, "M5": 5, "H1": 60, "D1": 1440}[self.settings.signal_timeframe])
            if not 0 <= (utcnow() - candle_close).total_seconds() <= 600:
                return self._skip_trade(session, signal, result, "Signal candle is incomplete or stale")
            # Other gates may perform network work; validate again before reserving an entry.
            final_reason = self._final_entry_check(signal)
            if final_reason:
                return self._skip_trade(session, signal, result, final_reason)
            from src.execution.risk_manager import notional_unit_cap
            final_quote = self._quotes[symbol]
            notional_price = max(quality["worst_entry"], signal.entry or signal.price, final_quote.ask)
            final_units = min(decision.units, notional_unit_cap(self.settings, account, notional_price, quote_fx))
            signal.decision_context["order_value"] = {
                "balance": account.balance, "account_currency": account.currency,
                "cap_fraction": self.settings.max_order_notional_pct,
                "sizing_price": notional_price, "units": final_units,
                "planned_value_usd": final_units * notional_price * quote_fx,
            }
            signal.decision_context["risk"]["units"] = final_units
            if final_units < 1:
                return self._skip_trade(session, signal, result, "Order-value cap does not permit one unit")
            if not claim_entry(self.broker.account_id, symbol, str(candle)):
                return self._skip_trade(session, signal, result, "Entry already attempted for this candle")
            row = insert_signal(session, signal.to_row())
            session.flush()
            trade = self._execute(session, signal, row.id, final_units, account)
            result["order_placed"] = bool(trade and trade.status in {"open", "partial"})
            result["trade_id"] = trade.broker_trade_id if trade else None
            result["size_mode"] = decision.size_mode
        return result

    def _skip_trade(
        self,
        session: Session,
        signal: TradeSignal,
        result: dict[str, Any],
        reason: str,
        *,
        extra_slack: bool = False,
    ) -> dict[str, Any]:
        """Record a blocked ticket. Sticky skips (underwater add-on, spread, halt) do not re-Slack every M5."""
        insert_signal(session, signal.to_row(skipped=True, skip_reason=reason))
        result["skipped"] = reason
        sticky = is_sticky_skip(reason)
        key = f"{signal.action}|{reason}"
        pulse = timedelta(minutes=max(5, self.settings.slack_pulse_minutes))
        repeat = (
            sticky
            and key == self._last_tape_key
            and self._last_tape_write is not None
            and utcnow() - self._last_tape_write < pulse
        )
        if repeat:
            logger.debug("Sticky skip still in force: {}", reason)
            result["quiet"] = True
            return result
        self._write_tape(session, signal, skip_reason=reason)
        if extra_slack and not sticky:
            try:
                self.slack.signal(signal, order_status=f"Skipped — {reason}", session=session)
            except Exception:
                logger.exception("Slack notify failed for skipped signal")
        elif sticky:
            logger.info("Skip {} {} — {}", signal.action, signal.symbol, reason)
        return result

    def _write_tape(
        self,
        session: Session,
        signal: TradeSignal,
        *,
        skip_reason: str | None = None,
        force_slack: bool = False,
    ) -> None:
        key = f"{signal.action}|{skip_reason or signal.reason}"
        pulse = timedelta(minutes=max(5, self.settings.slack_pulse_minutes))
        if (
            (
                (signal.action == "HOLD" and not skip_reason and not force_slack)
                or (skip_reason and is_sticky_skip(skip_reason) and not force_slack)
            )
            and key == self._last_tape_key
            and self._last_tape_write is not None
            and utcnow() - self._last_tape_write < pulse
        ):
            return
        body = build_tape_reflection(signal, skip_reason=skip_reason)
        note = insert_tape_note(
            session,
            {
                "ts": utcnow(),
                "symbol": signal.symbol,
                "timeframe": signal.timeframe,
                "action": signal.action,
                "price": signal.price,
                "strength": signal.strength,
                "reason": skip_reason or signal.reason,
                "body": body,
                "skip_reason": skip_reason,
                "indicators": {
                    "rsi": signal.rsi,
                    "stoch_k": signal.stoch_k,
                    "macd": signal.macd,
                    "macd_hist": signal.macd_hist,
                    "adx": signal.adx,
                    "cci": signal.cci,
                    "htf_bias": signal.htf_bias,
                    "d1_bias": signal.d1_bias,
                },
                "posted": False,
            },
        )
        slack_now = force_slack or signal.action in {"BUY", "SELL"} or bool(skip_reason)
        if not slack_now:
            elapsed = None if self._last_tape_slack is None else utcnow() - self._last_tape_slack
            slack_now = elapsed is None or elapsed >= pulse
        if slack_now:
            try:
                posted = self.slack.tape(
                    body, symbol=signal.symbol, action=signal.action, session=session
                )
                note.posted = posted
            except Exception:
                logger.exception("Slack tape post failed")
            self._last_tape_slack = utcnow()
        self._last_tape_write = utcnow()
        self._last_tape_key = key

    def send_tape_pulse(self) -> dict[str, Any]:
        """Force a written tape read onto the hub and into #forex."""
        with session_scope() as session:
            rows = load_bars(session, "EUR/USD", self.settings.signal_timeframe, limit=300)
            htf_rows = load_bars(session, "EUR/USD", self.settings.htf_bias_timeframe, limit=250)
            d1_rows = load_bars(session, "EUR/USD", "D1", limit=180)
            if not rows:
                return {"ok": False, "error": "no EUR/USD bars yet"}
            signal = evaluate_signal(
                "EUR/USD",
                self.settings.signal_timeframe,
                bars_to_frame(rows),
                htf_bars=bars_to_frame(htf_rows),
                d1_bars=bars_to_frame(d1_rows),
                settings=self.settings,
            )
            self._write_tape(session, signal, force_slack=True)
            return {"ok": True, "action": signal.action, "reason": signal.reason}

    def _playbook_context(self, session: Session) -> dict[str, Any]:
        return {
            "lessons": [
                _lesson_dict(r)
                for r in get_active_learned_rules(session)
                if r.action in {"skip", "require_high_strength", "prefer"}
            ][:12],
            "journals": [_journal_dict(j) for j in get_recent_journals(session, 12)],
            "open_trades": [_trade_dict(t) for t in get_open_trades(session)],
        }

    def refresh_history(self, *, force: bool = False) -> dict[str, Any]:
        """Parse extra datasets/, replay the live EMA/RSI idea, rewrite HISTORY.md."""
        try:
            from src.data.forexsb import ensure_eurusd_history

            ensure_eurusd_history(force=False)
        except Exception:
            logger.exception("ForexSB EUR/USD download failed")
        report = study_extra_datasets(force=force, persist=True)
        self._history = report
        path = write_history(report)
        if self._last_history_focus != report.next_focus:
            try:
                if report.files or report.rules:
                    append_learning("Historical study", [report.next_focus, *report.rules[:3]])
            except Exception:
                logger.exception("History log append failed")
            self._last_history_focus = report.next_focus
        logger.info(
            "History found={} files={} eurusd_bars={} preferred={} session={}",
            report.found,
            len(report.files),
            report.eurusd_bars,
            report.preferred_side,
            report.preferred_session,
        )
        payload = report.as_dict()
        payload["ok"] = True
        payload["path"] = str(path)
        return payload

    def kick_history_study(self, *, force: bool = False) -> bool:
        """Restudy extra datasets off the live quote/minute/intel clock."""
        with self._history_lock:
            if self._history_studying or (
                self._history_thread is not None and self._history_thread.is_alive()
            ):
                logger.debug("History study already running — not starting another")
                return False
            self._history_studying = True

        def _run() -> None:
            try:
                self.refresh_history(force=force)
            except Exception:
                logger.exception("Background history study failed")
            finally:
                self._history_studying = False

        self._history_thread = threading.Thread(
            target=_run, daemon=True, name="history-study"
        )
        self._history_thread.start()
        logger.info("History study kicked on a background thread")
        return True

    def kick_sheets_sync(self) -> bool:
        """Rewrite the Google Sheets book off the quote clock."""
        if not getattr(self.settings, "sheets_sync_enabled", True):
            return False
        with self._sheets_lock:
            if self._sheets_thread is not None and self._sheets_thread.is_alive():
                logger.debug("Sheets sync already running")
                return False

        def _run() -> None:
            try:
                self.sheets.settings = self.settings
                publish_from_db(
                    settings=self.settings,
                    account=self._account,
                    publisher=self.sheets,
                )
            except Exception:
                logger.exception("Google Sheets sync failed")

        self._sheets_thread = threading.Thread(target=_run, daemon=True, name="sheets-sync")
        self._sheets_thread.start()
        return True

    def connect_sheets(
        self,
        *,
        composio_api_key: str = "",
        spreadsheet_id: str = "",
        connected_account_id: str = "",
    ) -> dict[str, Any]:
        from src.config import reload_settings, upsert_env_values
        from src.notifications.sheets import parse_spreadsheet_id

        updates: dict[str, str] = {}
        key = (composio_api_key or "").strip()
        sid_raw = (spreadsheet_id or "").strip()
        sid = parse_spreadsheet_id(sid_raw)
        account = (connected_account_id or "").strip()
        if key:
            updates["COMPOSIO_API_KEY"] = key
        if sid:
            updates["GOOGLE_SHEETS_SPREADSHEET_ID"] = sid
            if sid_raw.startswith("http"):
                updates["GOOGLE_SHEETS_SPREADSHEET_URL"] = sid_raw.split("?")[0]
            else:
                updates["GOOGLE_SHEETS_SPREADSHEET_URL"] = (
                    f"https://docs.google.com/spreadsheets/d/{sid}/edit"
                )
        if account:
            updates["COMPOSIO_CONNECTED_ACCOUNT_ID"] = account
        if not updates and not self.settings.composio_api_key.get_secret_value():
            return {
                "ok": False,
                "error": "Paste a Composio API key (and optionally a spreadsheet ID) so the desk can push the book.",
            }
        if updates:
            upsert_env_values(updates)
            self.settings = reload_settings()
            self.sheets.settings = self.settings
        started = self.kick_sheets_sync()
        status = self.sheets.status()
        return {"ok": True, "started": started, **status}

    def refresh_growth(self, session: Session | None = None) -> dict[str, Any]:
        """Re-score the EUR/USD book, unban profitable setups, rewrite GROWTH.md.

        Does not walk ForexSB history — that restudy is kicked off-clock.
        """

        def _run(sess: Session) -> dict[str, Any]:
            restudy_learned_rules(sess, self.settings)
            report = study_book(sess, symbol="EUR/USD", settings=self.settings)
            if self._history is not None:
                extra = [rule for rule in self._history.rules if rule and rule not in report.rules]
                if extra:
                    report.rules = (report.rules + extra)[:10]
                if self._history.next_focus and "Waiting on historical" not in self._history.next_focus:
                    if not report.next_focus or "sample is still thin" in report.next_focus:
                        report.next_focus = self._history.next_focus
            self._growth = report
            path = write_growth(report)
            if self._last_growth_focus != report.next_focus:
                try:
                    append_learning("Growth study", [report.next_focus, *report.rules[:3]])
                except Exception:
                    logger.exception("Growth log append failed")
                self._last_growth_focus = report.next_focus
            logger.info(
                "Growth focus={} stop_floor={:.1f}p preferred={}",
                report.next_focus[:90],
                report.recommended_min_stop_pips,
                report.preferred_side,
            )
            payload = report.as_dict()
            payload["ok"] = True
            payload["path"] = str(path)
            payload["markdown"] = None
            payload["history"] = None if self._history is None else self._history.as_dict()
            return payload

        if session is not None:
            return _run(session)
        with session_scope() as sess:
            return _run(sess)

    def run_intel(self, *, force_slack: bool = True) -> dict[str, Any]:
        """Price consistency + EUR/USD news/macro → playbook + #forex."""
        try:
            self.fetcher.ensure_reference_mids(self.settings.symbols)
        except Exception:
            logger.debug("CurrencyFreaks refresh during intel failed")
        quote = self._quotes.get("EUR/USD")
        if quote is None:
            try:
                fetched = self.fetcher.fetch_quotes(["EUR/USD"])
                if fetched:
                    quote = fetched[0]
                    self._quotes["EUR/USD"] = quote
            except Exception:
                logger.debug("OANDA quote during intel failed")
        m5_close = None
        h1_bias = "neutral"
        d1_bias = "neutral"
        with session_scope() as session:
            from src.data.storage import latest_bar

            m5 = latest_bar(session, "EUR/USD", "M5")
            if m5 is not None:
                m5_close = float(m5.close)
            rows = load_bars(session, "EUR/USD", "M5", limit=220)
            htf_rows = load_bars(session, "EUR/USD", "H1", limit=180)
            d1_rows = load_bars(session, "EUR/USD", "D1", limit=120)
            if rows:
                signal = evaluate_signal(
                    "EUR/USD",
                    "M5",
                    bars_to_frame(rows),
                    htf_bars=bars_to_frame(htf_rows),
                    d1_bars=bars_to_frame(d1_rows),
                    settings=self.settings,
                )
                h1_bias = signal.htf_bias
                d1_bias = signal.d1_bias
        te = fetch_eurusd_snapshot()
        fxs = fetch_fxstreet_snapshot()
        bc = fetch_barchart_snapshot()
        inv = fetch_investing_snapshot()
        tv = fetch_tradingview_snapshot()
        tvq = fetch_tradingview_quote()
        ff = fetch_forexfactory_snapshot()
        price = check_price_consistency(
            oanda_mid=quote.mid if quote else None,
            cf_mid=self.fetcher.reference_mids.get("EUR/USD"),
            m5_close=m5_close,
            spread=quote.spread if quote else None,
            quote_ts=quote.ts if quote else None,
            warn_pips=float(self.settings.quote_warn_pips),
            te_mid=te.last,
            fxs_mid=fxs.last,
            bc_mid=bc.last,
            inv_mid=inv.last,
            tv_mid=tvq.last,
            cf_as_of=self.fetcher.reference_as_of,
        )
        bundle = self.news.refresh(
            tavily_key=self.settings.tavily_api_key.get_secret_value(),
            force=True,
        )
        macro = fetch_macro_tape()
        report = build_intel_report(
            price=price,
            bundle=bundle,
            macro=macro,
            h1_bias=h1_bias,
            d1_bias=d1_bias,
            te=te,
            fxs=fxs,
            bc=bc,
            inv=inv,
            tv=tv,
            tvq=tvq,
            ff=ff,
        )
        self._intel = report
        self._last_intel_at = report.ts
        posted = False
        with session_scope() as session:
            grown = self.refresh_growth(session=session)
            ctx = self._playbook_context(session)
            extra = list((self._growth.rules if self._growth else [])[:6])
            if self._history:
                extra.extend(rule for rule in self._history.rules[:4] if rule not in extra)
            path = publish_intel(
                report, **ctx, extra_rules=extra, log_title="Intel cycle"
            )
            if force_slack:
                try:
                    posted = self.slack.intel(report, session=session)
                except Exception:
                    logger.exception("Slack intel post failed")
        logger.info(
            "Intel {} EUR/USD verdict={} stance={}",
            report.ts.strftime("%H:%M UTC"),
            price.verdict,
            report.stance[:80],
        )
        payload = report.as_dict()
        payload["ok"] = True
        payload["playbook_path"] = str(path)
        payload["slack_posted"] = posted
        payload["growth"] = grown
        try:
            from src.analysis.news_patterns import harvest_and_score

            mid = quote.mid if quote else None
            news_score = harvest_and_score(
                bundle.headlines,
                price=mid,
                scan_kind="intel",
            )
            payload["news_log"] = {
                "added": news_score.get("added"),
                "stored": news_score.get("stored"),
                "pending": news_score.get("pending"),
            }
        except Exception:
            logger.exception("EUR/USD news ingest during intel failed")
        try:
            self.kick_sheets_sync()
        except Exception:
            logger.exception("Sheets sync after intel failed")
        return payload

    def playbook_payload(self) -> dict[str, Any]:
        from src.analysis.playbook import read_growth, read_history, read_tradingeconomics, read_fxstreet, read_barchart, read_investing, read_tradingview, read_forexfactory, read_mt4, read_operating, read_scalping, read_mistakes, read_sheets, read_news, read_news_patterns

        return {
            "path": str(PLAYBOOK_PATH),
            "playbook": read_playbook(),
            "learning_log": read_learning_log(),
            "growth": read_growth(),
            "history": read_history(),
            "tradingeconomics": read_tradingeconomics(),
            "fxstreet": read_fxstreet(),
            "barchart": read_barchart(),
            "investing": read_investing(),
            "tradingview": read_tradingview(),
            "forexfactory": read_forexfactory(),
            "mt4": read_mt4(),
            "operating": read_operating(),
            "scalping": read_scalping(),
            "mistakes": read_mistakes(),
            "sheets": read_sheets(),
            "news": read_news(),
            "news_patterns": read_news_patterns(),
            "intel": None if self._intel is None else self._intel.as_dict(),
            "study": None if self._growth is None else self._growth.as_dict(),
            "history_study": None if self._history is None else self._history.as_dict(),
            "updated_at": None if self._last_intel_at is None else self._last_intel_at.isoformat(),
        }

    def _ingest_journal_into_playbook(self, journal) -> None:
        if journal is None:
            return
        title = f"{journal.side} {journal.symbol} {journal.outcome or 'open'}"
        bullets = [
            (journal.lesson or journal.how_to_avoid or journal.entry_thesis or "")[:400],
            f"P/L ${float(journal.realized_pl or 0):+.2f} via {journal.close_reason or 'n/a'}",
        ]
        try:
            append_learning(title, bullets)
        except Exception:
            logger.exception("Learning log append failed")
        try:
            self.refresh_growth()
        except Exception:
            logger.exception("Growth restudy after journal failed")
        try:
            self.kick_sheets_sync()
        except Exception:
            logger.exception("Sheets sync after journal failed")

    def connect_slack(
        self,
        *,
        bot_token: str = "",
        webhook_url: str = "",
        channel: str = "forex",
    ) -> dict[str, Any]:
        from src.config import reload_settings, upsert_env_values

        token = (bot_token or "").strip()
        webhook = (webhook_url or "").strip()
        channel_name = (channel or "forex").strip().lstrip("#") or "forex"
        updates: dict[str, str] = {"SLACK_CHANNEL": channel_name}
        if token:
            updates["SLACK_BOT_TOKEN"] = token
        if webhook:
            updates["SLACK_WEBHOOK_URL"] = webhook
        if not token and not webhook and not self.settings.slack_enabled:
            return {
                "ok": False,
                "error": "Paste a Slack bot token (xoxb-...) or an incoming webhook URL for #forex",
            }
        upsert_env_values(updates)
        # An explicit dashboard connection may override this process's launch-time
        # empty credentials. Do not silently discard the token just saved to .env.
        import os
        for key in ("SLACK_BOT_TOKEN", "SLACK_WEBHOOK_URL", "SLACK_CHANNEL"):
            if key in updates:
                os.environ[key] = updates[key]
        self.settings = reload_settings()
        self.slack.apply_credentials(self.settings)
        ok, detail = self.slack.ensure_channel()
        replayed = 0
        if ok:
            self.slack.startup_ping()
            with session_scope() as session:
                replayed = self.slack.replay_outbox(session)
            try:
                self.send_tape_pulse()
            except Exception:
                logger.exception("Tape pulse after Slack connect failed")
        return {
            "ok": ok,
            "detail": detail,
            "replayed": replayed,
            "ready": self.slack._ready,
            "channel": self.slack.target_label,
        }

    def connect_mt4(
        self,
        *,
        login: str,
        password: str,
        server: str,
        metaapi_token: str = "",
        enabled: bool = True,
    ) -> dict[str, Any]:
        result = self.mt4.connect(
            login=login,
            password=password,
            server=server,
            metaapi_token=metaapi_token,
            enabled=enabled,
        )
        from src.config import reload_settings

        self.settings = reload_settings()
        self.mt4.settings = self.settings
        return result

    def apply_mt4_bridge(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.mt4.apply_bridge(payload)

    def _exec_broker(self, trade: Trade):
        venue = str(getattr(trade, "venue", "oanda") or "oanda").lower()
        if venue == VENUE_MT4:
            return self.mt4
        return self.broker

    def _mirror_mt4(self, session: Session, trade: Trade, signal: TradeSignal) -> Trade | None:
        """Copy a successful OANDA fill onto the MT4 demo. Failure leaves OANDA open."""
        if not self.settings.mt4_enabled or not self.mt4.credentials_ready:
            return None
        side = str(trade.side or "").upper()
        try:
            report = self.mt4.place_market_order(
                symbol=trade.symbol,
                side=side,
                units=int(trade.units or 0),
                stop_loss=float(trade.stop_loss or 0),
                take_profit=float(trade.take_profit_2 or trade.take_profit_1 or 0),
                requested_entry=float(trade.fill_price or trade.requested_entry or signal.price),
                comment=f"fs-{trade.broker_trade_id or trade.id}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MT4 copy of OANDA #{} failed (OANDA stays): {}", trade.broker_trade_id, exc)
            return None
        if not report.ok:
            logger.warning(
                "MT4 copy of OANDA #{} rejected (OANDA stays): {}",
                trade.broker_trade_id,
                report.error,
            )
            return None
        copy = insert_trade(
            session,
            {
                "broker_order_id": report.broker_order_id,
                "broker_trade_id": report.broker_trade_id,
                "signal_id": trade.signal_id,
                "parent_trade_id": trade.id,
                "symbol": trade.symbol,
                "side": side,
                "units": report.units or trade.units,
                "requested_entry": trade.requested_entry,
                "fill_price": report.fill_price,
                "slippage_pips": report.slippage_pips,
                "stop_loss": report.stop_loss or trade.stop_loss,
                "take_profit_1": trade.take_profit_1,
                "take_profit_2": report.take_profit or trade.take_profit_2,
                "broker_take_profit": report.take_profit or trade.take_profit_2,
                "status": "open",
                "remaining_units": report.units or trade.units,
                "source": SOURCE_BOT,
                "venue": VENUE_MT4,
                "opened_at": utcnow(),
            },
        )
        logger.info(
            "MT4 {} {} lots={} ticket={} (copy of OANDA #{})",
            side,
            trade.symbol,
            abs(int(report.units or trade.units or 0)) / 100_000.0,
            report.broker_trade_id,
            trade.broker_trade_id,
        )
        return copy

    def _mirror_mt4_close(self, session: Session, trade: Trade, *, units: str = "ALL") -> None:
        copy = get_mt4_sibling(session, trade)
        if copy is None or not copy.broker_trade_id:
            return
        try:
            payload = self.mt4.close_trade(str(copy.broker_trade_id), units=units)
            exit_price, realized = self.mt4.realized_pl_from_close(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MT4 copy close of #{} failed: {}", copy.broker_trade_id, exc)
            return
        if units == "ALL":
            copy.status = "closed"
            copy.remaining_units = 0
            copy.closed_at = utcnow()
            copy.close_reason = trade.close_reason or "oanda_mirror"
            if exit_price:
                copy.exit_price = float(exit_price)
            if realized is not None:
                copy.realized_pl = float(copy.realized_pl or 0) + float(realized)
            elif copy.fill_price:
                quote = self._quotes.get(copy.symbol)
                mid = float(exit_price or (quote.mid if quote is not None else 0) or copy.fill_price)
                from src.execution.mt4 import realized_pl_usd

                copy.realized_pl = realized_pl_usd(
                    side=copy.side,
                    fill=float(copy.fill_price),
                    exit_price=mid,
                    units=int(copy.units or 0),
                )
                copy.exit_price = copy.exit_price or mid
        else:
            try:
                half = int(float(units))
            except (TypeError, ValueError):
                half = 0
            copy.tp1_filled = True
            copy.status = "partial"
            copy.remaining_units = max(0, int(copy.remaining_units or copy.units or 0) - half)
            if realized:
                copy.realized_pl = float(copy.realized_pl or 0) + float(realized)
            try:
                self.mt4.modify_trade(
                    str(copy.broker_trade_id),
                    symbol=copy.symbol,
                    stop_loss=float(copy.fill_price or 0),
                    take_profit=float(copy.take_profit_2 or 0),
                )
                if copy.fill_price:
                    copy.stop_loss = float(copy.fill_price)
            except Exception as exc:
                logger.warning("MT4 copy trail to breakeven failed: {}", exc)

    def _final_entry_check(self, signal):
        if getattr(self.settings, "strategy_research_only", False):
            return "Strategy research-only: no validated improvement; new orders disabled"
        from src.analysis.entry_quality import entry_quality
        from src.analysis.mistakes import cost_eats_stop
        try:
            quote = next((q for q in self.fetcher.fetch_quotes([signal.symbol])
                          if q.symbol == signal.symbol), None)
        except Exception:
            return "Entry quality: final quote refresh failed"
        if not self._management_quote_ready(quote):
            return "Entry quality: final quote is not fresh tradeable OANDA bid/ask"
        self._quotes[signal.symbol] = quote
        quality = entry_quality(signal, quote, self.settings)
        signal.decision_context = dict(signal.decision_context or {})
        quality["quote_at"] = quote.ts.isoformat()
        quality["bid"] = quote.bid
        quality["ask"] = quote.ask
        signal.decision_context["final_entry_quality"] = quality
        if not quality["allowed"]:
            return quality["reason"]
        spread = price_to_pips(signal.symbol, quote.ask - quote.bid)
        stop_pips = price_to_pips(signal.symbol, abs(quality["executable_entry"] - signal.stop_loss))
        from src.analysis.sampling import sampling_policy
        if spread > self.settings.scalp_max_spread_pips or cost_eats_stop(spread, stop_pips, sampling_policy(self.settings)["cost_stop_fraction"]):
            return "Entry quality: final spread exceeds the spread/cost limits"
        if calendar_hold_reason(utcnow(), settings=self.settings):
            return "Entry quality: calendar entry window closed"
        if not self.trading_enabled:
            return "Trading paused from dashboard"
        return None

    def _submit_order(self, signal, side, units, pattern_name):
        if getattr(self.settings, "strategy_research_only", False):
            raise ValueError("Strategy research-only: new orders disabled")
        return self.broker.place_market_order(
            symbol=signal.symbol,
            side=side,
            units=units,
            stop_loss=signal.stop_loss or 0.0,
            take_profit=signal.take_profit_2 or signal.take_profit_1 or 0.0,
            requested_entry=signal.entry or signal.price,
            comment=oanda_trade_comment(side=side, signal=signal, pattern_name=pattern_name),
        )

    def _execute(
        self,
        session: Session,
        signal: TradeSignal,
        signal_id: int,
        units: int,
        account: AccountState,
    ) -> Trade | None:
        side = "BUY" if signal.action == "BUY" else "SELL"
        pattern_name = ""
        try:
            recent = load_bars(session, signal.symbol, "M5", limit=80)
            candles = [
                {
                    "time": int(row.ts.timestamp()) if getattr(row.ts, "timestamp", None) else 0,
                    "open": float(row.open),
                    "high": float(row.high),
                    "low": float(row.low),
                    "close": float(row.close),
                }
                for row in recent
            ]
            pattern_name = latest_setup_label(candles)
        except Exception:
            logger.debug("Pattern stamp for OANDA comment unavailable")
        try:
            report = self._submit_order(signal, side, units, pattern_name)
        except Exception:
            self.trading_enabled = False
            logger.exception("Order submission unresolved; new entries paused pending reconciliation")
            raise
        status = "open" if report.ok else "rejected"
        trade = insert_trade(
            session,
            {
                "broker_order_id": report.broker_order_id,
                "broker_trade_id": report.broker_trade_id,
                "signal_id": signal_id,
                "symbol": signal.symbol,
                "side": side,
                "units": report.units or units,
                "requested_entry": signal.entry or signal.price,
                "fill_price": report.fill_price,
                "slippage_pips": report.slippage_pips,
                "stop_loss": report.stop_loss or signal.stop_loss or 0.0,
                "take_profit_1": signal.take_profit_1 or 0.0,
                "take_profit_2": report.take_profit or signal.take_profit_2 or signal.take_profit_1 or 0.0,
                "broker_take_profit": report.take_profit or signal.take_profit_2 or signal.take_profit_1 or 0.0,
                "status": status,
                "remaining_units": report.units or units if report.ok else 0,
                "error_message": report.error,
                "source": SOURCE_BOT,
                "venue": "oanda",
                "opened_at": utcnow() if report.ok else None,
            },
        )
        daily = get_or_create_daily_pnl(session, utcnow().date(), account.balance)
        if report.ok:
            daily.trades_opened += 1
            journal = record_entry(session, trade, signal)
            session.flush()
            try:
                self._mirror_mt4(session, trade, signal)
            except Exception:
                logger.exception("MT4 mirror after OANDA fill failed (OANDA #{} stays)", report.broker_trade_id)
            try:
                session.commit()
            except Exception:
                self.trading_enabled = False
                self.broker.client.pause_writes("Fill received but local record commit failed")
                logger.exception("Failed to commit fill record; paused for reconciliation")
                raise
            order_label = f"Demo Order Placed (#{report.broker_trade_id})"
            try:
                self.slack.signal(
                    signal, order_status=order_label, lot_size=report.units, session=session
                )
                self.slack.fill(
                    session=session,
                    symbol=signal.symbol,
                    side=side,
                    trade_id=str(report.broker_trade_id),
                    units=report.units,
                    fill_price=report.fill_price or signal.price,
                    stop_loss=signal.stop_loss or 0.0,
                    take_profit=signal.take_profit_2 or signal.take_profit_1 or 0.0,
                    slippage_pips=report.slippage_pips,
                )
                self.slack.journal(journal, session=session)
            except Exception:
                logger.exception("Slack notify failed after fill")
            self._ingest_journal_into_playbook(journal)
            try:
                self.broker.annotate_trade(
                    str(report.broker_trade_id),
                    comment=oanda_thesis_comment(journal.entry_thesis),
                )
            except Exception:
                logger.exception("OANDA chart comment failed")
            logger.info(
                "Filled {} {} #{} @{} units={}",
                side,
                signal.symbol,
                report.broker_trade_id,
                report.fill_price,
                report.units,
            )
        else:
            try:
                self.slack.signal(
                    signal, order_status=f"Rejected — {report.error}", session=session
                )
            except Exception:
                logger.exception("Slack notify failed after reject")
            err = str(report.error or "")
            if "FIFO" in err.upper():
                self._fifo_block[f"{signal.symbol}|{side}"] = err
                logger.warning(
                    "OANDA FIFO blocked {} {} — will not retry until that ticket is gone ({})",
                    side,
                    signal.symbol,
                    err,
                )
            else:
                logger.error("Order rejected: {}", report.error)
        return trade

    def _store_latest_indicators(self, session: Session, symbol: str, timeframe: str) -> None:
        rows = load_bars(session, symbol, timeframe, limit=300)
        frame = bars_to_frame(rows)
        if frame.empty:
            return
        computed = compute_indicators(
            frame,
            ema_fast=self.settings.ema_fast,
            ema_slow=self.settings.ema_slow,
            rsi_period=self.settings.rsi_period,
            atr_period=self.settings.atr_period,
            bb_period=self.settings.bb_period,
            bb_std=self.settings.bb_std,
        )
        payloads = []
        ready = computed.dropna(subset=["ema_fast", "ema_slow", "rsi", "atr", "bb_mid"])
        # Persist only the last 30 computed rows each cycle to keep writes cheap.
        for ts, row in ready.tail(30).iterrows():
            ts_val = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            if isinstance(ts_val, datetime) and ts_val.tzinfo is None:
                ts_val = ts_val.replace(tzinfo=timezone.utc)
            payloads.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "ts": ts_val,
                    "ema_fast": float(row["ema_fast"]),
                    "ema_slow": float(row["ema_slow"]),
                    "rsi": float(row["rsi"]),
                    "atr": float(row["atr"]),
                    "bb_upper": float(row["bb_upper"]),
                    "bb_mid": float(row["bb_mid"]),
                    "bb_lower": float(row["bb_lower"]),
                    "macd": float(row["macd"]) if row.get("macd") == row.get("macd") else None,
                    "macd_signal": float(row["macd_signal"]) if row.get("macd_signal") == row.get("macd_signal") else None,
                    "macd_hist": float(row["macd_hist"]) if row.get("macd_hist") == row.get("macd_hist") else None,
                    "stoch_k": float(row["stoch_k"]) if row.get("stoch_k") == row.get("stoch_k") else None,
                    "stoch_d": float(row["stoch_d"]) if row.get("stoch_d") == row.get("stoch_d") else None,
                    "adx": float(row["adx"]) if row.get("adx") == row.get("adx") else None,
                    "plus_di": float(row["plus_di"]) if row.get("plus_di") == row.get("plus_di") else None,
                    "minus_di": float(row["minus_di"]) if row.get("minus_di") == row.get("minus_di") else None,
                    "cci": float(row["cci"]) if row.get("cci") == row.get("cci") else None,
                    "trend": int(row["trend"]) if row.get("trend") == row.get("trend") else None,
                    "extra": {
                        "bb_pct": float(row["bb_pct"]) if row.get("bb_pct") == row.get("bb_pct") else None,
                        "trend": int(row["trend"]),
                        "macd": float(row["macd"]) if row.get("macd") == row.get("macd") else None,
                        "macd_signal": float(row["macd_signal"]) if row.get("macd_signal") == row.get("macd_signal") else None,
                        "macd_hist": float(row["macd_hist"]) if row.get("macd_hist") == row.get("macd_hist") else None,
                        "stoch_k": float(row["stoch_k"]) if row.get("stoch_k") == row.get("stoch_k") else None,
                        "stoch_d": float(row["stoch_d"]) if row.get("stoch_d") == row.get("stoch_d") else None,
                        "adx": float(row["adx"]) if row.get("adx") == row.get("adx") else None,
                        "plus_di": float(row["plus_di"]) if row.get("plus_di") == row.get("plus_di") else None,
                        "minus_di": float(row["minus_di"]) if row.get("minus_di") == row.get("minus_di") else None,
                        "cci": float(row["cci"]) if row.get("cci") == row.get("cci") else None,
                        "vwap": float(row["vwap"]) if row.get("vwap") == row.get("vwap") else None,
                        "supertrend": float(row["supertrend"]) if row.get("supertrend") == row.get("supertrend") else None,
                        "st_dir": float(row["st_dir"]) if row.get("st_dir") == row.get("st_dir") else None,
                        "squeeze_on": bool(row.get("squeeze_on")),
                        "wt1": float(row["wt1"]) if row.get("wt1") == row.get("wt1") else None,
                        "ewmac": float(row["ewmac"]) if row.get("ewmac") == row.get("ewmac") else None,
                        "tma": float(row["tma"]) if row.get("tma") == row.get("tma") else None,
                    },
                }
            )
        upsert_indicators(session, payloads)

    def _persist_snapshot(self, account: AccountState) -> None:
        with session_scope() as session:
            hist_peak = peak_nav(session, fallback=account.nav)
            peak = max(hist_peak, account.nav)
            dd = (peak - account.nav) / peak if peak else 0.0
            session.add(
                AccountSnapshot(
                    ts=utcnow(),
                    balance=account.balance,
                    nav=account.nav,
                    unrealized_pl=account.unrealized_pl,
                    realized_pl=account.realized_pl,
                    margin_used=account.margin_used,
                    margin_available=account.margin_available,
                    open_trade_count=account.open_trade_count,
                    peak_nav=peak,
                    drawdown_pct=dd,
                    raw=account.raw,
                )
            )
            get_or_create_daily_pnl(session, utcnow().date(), account.balance)

    def _flatten_off_watchlist(self) -> None:
        """Close stamped desk positions outside the watchlist; leave humans alone."""
        allowed = set(self.settings.symbols)
        try:
            remote = self.broker.open_trades()
        except Exception as exc:
            logger.warning("Could not list trades to flatten: {}", exc)
            return
        for row in remote:
            if classify_remote_trade(row) != SOURCE_BOT:
                continue
            symbol = canonical_pair(to_display_symbol(row.get("instrument", "")))
            if symbol in allowed:
                continue
            tid = str(row.get("id"))
            try:
                self.broker.close_trade(tid, units="ALL")
                logger.info("Flattened {} #{} — specialist desk is EUR/USD only", symbol, tid)
            except Exception as exc:
                logger.warning("Could not flatten {} #{}: {}", symbol, tid, exc)

    def _sync_open_trades(self, account: AccountState) -> None:
        """Reconcile local open trades with OANDA and manage TP1 partials."""
        try:
            listed = list(self.broker.open_trades())
            self._remote_open = listed
            remote = {str(t["id"]): t for t in listed}
        except Exception as exc:
            logger.warning("Could not list open trades: {}", exc)
            raise RuntimeError("Account reconciliation unavailable; no new entries") from exc
        with session_scope() as session:
            local = get_open_trades(session)
            oanda_local = [
                t for t in local if str(getattr(t, "venue", "oanda") or "oanda").lower() != VENUE_MT4
            ]
            known = {str(t.broker_trade_id) for t in oanda_local if t.broker_trade_id}
            for trade in oanda_local:
                remote_row = remote.get(str(trade.broker_trade_id))
                if remote_row is None and trade.broker_trade_id:
                    self._mark_closed_missing(session, trade, account)
                    continue
                if remote_row is None:
                    continue
                if classify_remote_trade(remote_row) == SOURCE_HUMAN:
                    trade.source = SOURCE_HUMAN
                    continue
                remaining = abs(int(float(remote_row.get("currentUnits") or 0)))
                if remaining < int(trade.remaining_units or 0):
                    # Recover a partial fill even if the process died before committing SQLite.
                    trade.tp1_filled = True
                    trade.status = "partial"
                trade.remaining_units = remaining
                trade.realized_pl = float(remote_row.get("realizedPL") or 0)
                for field, key in (("stop_loss", "stopLossOrder"), ("take_profit_2", "takeProfitOrder")):
                    level = (remote_row.get(key) or {}).get("price")
                    if level:
                        setattr(trade, field, float(level))
                self._maybe_take_partial(session, trade, remote_row)
                self._maybe_time_stop(session, trade, remote_row, account)
            for rid, remote_row in remote.items():
                if rid not in known:
                    symbol = canonical_pair(to_display_symbol(remote_row.get("instrument", "")))
                    if symbol not in self.settings.symbols:
                        continue
                    self._adopt_remote_trade(session, remote_row, venue="oanda")
            self._sync_mt4_trades(session, account)

    def _sync_mt4_trades(self, session: Session, account: AccountState) -> None:
        """Reconcile MT4 copies without letting them eat the OANDA book or flatten humans."""
        mode = self.mt4.mode()
        if mode in {"off", "disconnected"}:
            return
        try:
            listed = list(self.mt4.open_trades())
            remote = {str(t["id"]): t for t in listed if t.get("id")}
        except Exception as exc:
            logger.warning("Could not list MT4 trades: {}", exc)
            return
        local = [
            t for t in get_open_trades(session) if str(getattr(t, "venue", "oanda") or "oanda").lower() == VENUE_MT4
        ]
        known = {str(t.broker_trade_id) for t in local if t.broker_trade_id}
        live = mode in {"metaapi", "bridge"}
        for trade in local:
            tid = str(trade.broker_trade_id or "")
            if tid.startswith("ledger-") or tid.startswith("pending-"):
                continue
            if not live:
                continue
            if tid and tid not in remote:
                self._mark_closed_missing(session, trade, account)
        for rid, remote_row in remote.items():
            if rid in known:
                continue
            magic = int(remote_row.get("magic") or 0)
            if magic == self.mt4.magic:
                source = SOURCE_BOT
            else:
                source = SOURCE_HUMAN
            self._adopt_remote_trade(session, remote_row, venue=VENUE_MT4, source=source)

    def _adopt_remote_trade(
        self,
        session: Session,
        remote_row: dict[str, Any],
        *,
        venue: str = "oanda",
        source: str | None = None,
    ) -> Trade:
        """Persist a broker fill that was not committed locally (operator demo or crash)."""
        units = int(float(remote_row.get("currentUnits") or remote_row.get("initialUnits") or 0))
        initial_units = abs(int(float(remote_row.get("initialUnits") or units)))
        was_reduced = abs(units) < initial_units
        side = "BUY" if units > 0 else "SELL"
        fill = float(remote_row.get("price") or 0)
        source = source or classify_remote_trade(remote_row)
        levels = adopted_levels(remote_row, source=source)
        opened = remote_row.get("openTime")
        try:
            from src.utils import parse_iso

            opened_at = parse_iso(opened) if opened else utcnow()
        except Exception:
            opened_at = utcnow()
        trade = insert_trade(
            session,
            {
                "broker_order_id": str(remote_row.get("id")),
                "broker_trade_id": str(remote_row.get("id")),
                "symbol": to_display_symbol(remote_row.get("instrument", "")),
                "side": side,
                "units": initial_units,
                "requested_entry": fill,
                "fill_price": fill,
                "stop_loss": levels["stop_loss"],
                "take_profit_1": levels["take_profit_1"],
                "take_profit_2": levels["take_profit_2"],
                "broker_take_profit": levels["take_profit_2"],
                "status": "partial" if was_reduced else "open",
                "tp1_filled": was_reduced,
                "realized_pl": float(remote_row.get("realizedPL") or 0),
                "remaining_units": abs(units),
                "source": source,
                "venue": venue,
                "opened_at": opened_at,
                "close_reason": None,
            },
        )
        journal = record_entry(session, trade, adopted=True)
        logger.warning(
            "Adopted {} broker trade #{} {} {} @{} — {}",
            source,
            remote_row.get("id"),
            side,
            remote_row.get("instrument"),
            fill,
            "hands off" if source == SOURCE_HUMAN else "will manage TP1 if it pays",
        )
        try:
            self.slack.journal(journal, session=session)
        except Exception:
            logger.exception("Slack notify failed after adopt")
        self._ingest_journal_into_playbook(journal)
        return trade

    def _mark_closed_missing(self, session: Session, trade: Trade, account: AccountState) -> None:
        if str(getattr(trade, "venue", "oanda") or "oanda").lower() == "oanda":
            try:
                row = self.broker.trade_details(str(trade.broker_trade_id))
                if row.get("state") != "CLOSED":
                    raise ValueError("Broker has not confirmed closure")
                from src.utils import parse_iso
                exit_price = float(row["averageClosePrice"])
                realized = float(row["realizedPL"])
                closed_at = parse_iso(row["closeTime"])
                if not math.isfinite(exit_price) or not math.isfinite(realized) or exit_price <= 0:
                    raise ValueError("Invalid broker closing values")
            except Exception as exc:
                logger.warning("Close reconciliation deferred for {}: {}", trade.broker_trade_id, exc)
                raise RuntimeError("Unresolved broker closure; new entries blocked") from exc
            reason = "broker_closed"  # Do not guess stop/target from price proximity.
            if row.get("closingTransactionIDs"):
                try:
                    reason = self.broker.confirmed_close_reason(row)
                except Exception as exc:
                    # P/L and closure are already confirmed; missing attribution
                    # must not prevent position reconciliation or invent a cause.
                    logger.warning("Exit attribution unavailable for {}: {}", trade.broker_trade_id, exc)
            trade.source = classify_remote_trade(row)
            trade.closed_at = closed_at
        else:
            # MT4 still requires its own deal-history adapter.
            logger.warning("MT4 ticket {} missing; awaiting confirmed deal history", trade.broker_trade_id)
            return
        trade.status = "closed"
        trade.remaining_units = 0
        trade.exit_price = exit_price
        trade.realized_pl = realized
        trade.close_reason = reason
        if trade.source == SOURCE_HUMAN:
            return
        daily = get_or_create_daily_pnl(session, trade.closed_at.date(), account.balance)
        daily.trades_closed += 1
        journal = record_exit(
            session,
            trade,
            exit_price=exit_price,
            realized_pl=realized,
            close_reason=reason,
            settings=self.settings,
        )
        logger.info(
            "Trade #{} {} marked closed ({}) pl={:.2f}",
            trade.id,
            trade.symbol,
            reason,
            realized,
        )
        try:
            self.slack.postmortem(journal, session=session)
        except Exception:
            logger.exception("Slack post-mortem failed")
        self._ingest_journal_into_playbook(journal)
        try:
            self._mirror_mt4_close(session, trade, units="ALL")
        except Exception:
            logger.exception("MT4 copy close after missing OANDA ticket failed")

    def _maybe_take_partial(self, session: Session, trade: Trade, remote_row: dict[str, Any]) -> None:
        try:
            unrealized = float(remote_row.get("unrealizedPL") or 0)
        except (TypeError, ValueError):
            unrealized = 0.0
        quote = self._quotes.get(trade.symbol)
        if not self._management_quote_ready(quote):
            return
        current = quote.bid if trade.side.upper() == "BUY" else quote.ask
        ok, why = should_take_partial(trade, mark=current, unrealized_pl=unrealized)
        if not ok:
            if trade.source == SOURCE_HUMAN:
                logger.debug("Hands off operator {} #{}: {}", trade.symbol, trade.broker_trade_id, why)
            return
        half = partial_close_units(trade.remaining_units)
        if half < 1:
            return
        try:
            payload = self._exec_broker(trade).close_trade(str(trade.broker_trade_id), units=str(half))
            exit_price, realized = self._exec_broker(trade).realized_pl_from_close(payload)
            trade.tp1_filled = True
            trade.status = "partial"
            trade.remaining_units = max(0, trade.remaining_units - half)
            if realized:
                trade.realized_pl = float(trade.realized_pl) + float(realized)
            try:
                self._exec_broker(trade).modify_trade(
                    str(trade.broker_trade_id),
                    symbol=trade.symbol,
                    stop_loss=float(trade.fill_price),
                    take_profit=float(trade.take_profit_2),
                )
                trade.stop_loss = float(trade.fill_price)
            except Exception as exc:
                logger.warning("Could not trail SL to breakeven: {}", exc)
            logger.info(
                "TP1 hit on {} #{} closed {} units @{} ({})",
                trade.symbol,
                trade.broker_trade_id,
                half,
                exit_price,
                why,
            )
            try:
                self._mirror_mt4_close(session, trade, units=str(half))
            except Exception:
                logger.exception("MT4 copy TP1 failed")
        except Exception as exc:
            logger.warning("TP1 partial close failed: {}", exc)

    def _management_quote_ready(self, quote: Quote | None) -> bool:
        if quote is None or not quote.tradeable or quote.source != "oanda":
            return False
        ts = quote.ts if quote.ts.tzinfo else quote.ts.replace(tzinfo=timezone.utc)
        age = (utcnow() - ts).total_seconds()
        return (-5 <= age <= self.settings.stale_quote_seconds
                and math.isfinite(quote.bid) and math.isfinite(quote.ask)
                and 0 < quote.bid <= quote.ask)

    def _maybe_time_stop(
        self, session: Session, trade: Trade, remote_row: dict[str, Any], account: AccountState
    ) -> None:
        if getattr(self.settings, "trading_style", "scalp") != "scalp":
            return
        max_hold = float(getattr(self.settings, "scalp_max_hold_minutes", 90) or 90)
        ok, why = should_flatten_scalp(trade, now=utcnow(), max_hold_minutes=max_hold)
        now = utcnow()
        if not broker_market_hours(self.settings) and now.weekday() == 4 and now.hour >= self.settings.friday_flat_hour and trade.source == SOURCE_BOT:
            ok, why = True, "Friday flat"
        if not ok or not self._management_quote_ready(self._quotes.get(trade.symbol)):
            return
        if not trade.broker_trade_id:
            return
        try:
            payload = self._exec_broker(trade).close_trade(str(trade.broker_trade_id), units="ALL")
            exit_price, realized = self._exec_broker(trade).realized_pl_from_close(payload)
            trade.status = "closed"
            trade.remaining_units = 0
            trade.closed_at = utcnow()
            trade.close_reason = why
            if exit_price:
                trade.exit_price = float(exit_price)
            if realized is not None:
                trade.realized_pl = float(trade.realized_pl or 0) + float(realized)
            daily = get_or_create_daily_pnl(session, utcnow().date(), account.balance)
            daily.trades_closed += 1
            journal = record_exit(
                session,
                trade,
                exit_price=trade.exit_price,
                realized_pl=float(trade.realized_pl or 0),
                close_reason=why,
                settings=self.settings,
            )
            logger.info(
                "Scalp time-stop {} #{} after hold window ({})",
                trade.symbol,
                trade.broker_trade_id,
                why,
            )
            try:
                self.slack.postmortem(journal, session=session)
            except Exception:
                logger.exception("Slack post-mortem failed after scalp time stop")
            self._ingest_journal_into_playbook(journal)
            try:
                self._mirror_mt4_close(session, trade, units="ALL")
            except Exception:
                logger.exception("MT4 copy time-stop failed")
        except Exception as exc:
            logger.warning("Scalp time stop failed: {}", exc)

    def _resolve_close(
        self,
        trade: Trade,
        exit_price: float | None,
        realized: float | None,
    ) -> tuple[float | None, float, str]:
        """Fill in missing exit price / P/L and infer why the broker flattened."""
        quote = self._quotes.get(trade.symbol)
        mid = quote.mid if quote is not None else None
        price = exit_price or trade.exit_price or mid
        booked = float(trade.realized_pl or 0)
        if realized is not None:
            pl = booked + float(realized)
        elif abs(booked) > 1e-9:
            pl = booked
        elif price and trade.fill_price:
            fx = self.broker.quote_to_usd(trade.symbol, float(price))
            pl = estimate_realized_pl(trade, float(price), fx)
        else:
            pl = booked
        reason = infer_close_reason(trade, float(price) if price else None)
        return (float(price) if price else None), float(pl), reason

    def run_news_scan(self, *, force: bool = False, deep: bool = True) -> dict[str, Any]:
        """05:00 UTC harvest: log EUR/USD headlines, predict, later score vs M5."""
        from datetime import timezone as tz

        from sqlalchemy import func, select

        from src.analysis.news_patterns import append_news_log, harvest_and_score, review_news_outcomes, write_patterns
        from src.data.news import harvest_eurusd_news
        from src.data.storage import NewsItem

        now = utcnow()
        day_start = datetime(now.year, now.month, now.day, tzinfo=tz.utc)
        if not force:
            with session_scope() as session:
                already = int(
                    session.scalar(
                        select(func.count())
                        .select_from(NewsItem)
                        .where(NewsItem.scan_kind == "morning", NewsItem.ts >= day_start)
                    )
                    or 0
                )
            if already:
                with session_scope() as session:
                    reviewed = review_news_outcomes(session)
                    patterns = write_patterns(session)
                return {
                    "ok": True,
                    "skipped": "already scanned today",
                    "reviewed": reviewed,
                    "pattern_count": len(patterns),
                }

        quote = self._quotes.get("EUR/USD")
        if quote is None:
            try:
                fetched = self.fetcher.fetch_quotes(["EUR/USD"])
                if fetched:
                    quote = fetched[0]
                    self._quotes["EUR/USD"] = quote
            except Exception:
                logger.debug("OANDA quote during news scan failed")
        mid = quote.mid if quote else None
        headlines = harvest_eurusd_news(limit=160, deep=deep)
        result = harvest_and_score(
            headlines,
            price=mid,
            scan_kind="morning" if deep else "harvest",
        )
        bullets = [
            f"{result.get('added', 0)} new headlines stored (book {result.get('stored', 0)}, {result.get('pending', 0)} waiting on a later M5 close)",
            f"Revisited {result.get('reviewed', 0)} due items",
            f"Spot EUR/USD `{mid:.5f}`" if mid else "No live mid at scan — prices will fill on revisit",
        ]
        for item in headlines[:8]:
            bullets.append(f"{item.source}: {item.title}")
        try:
            append_news_log("Morning EUR/USD news scan" if deep else "EUR/USD news harvest", bullets)
        except Exception:
            logger.exception("News log append failed")
        try:
            self.slack.news_scan(result, headlines[:8], session=None)
        except Exception:
            logger.exception("Slack news scan failed")
        try:
            self.kick_sheets_sync()
        except Exception:
            logger.exception("Sheets sync after news scan failed")
        logger.info(
            "EUR/USD news scan added={} stored={} pending={}",
            result.get("added"),
            result.get("stored"),
            result.get("pending"),
        )
        result["headlines"] = [h.as_dict() for h in headlines[:12]]
        result["price"] = mid
        return result

    def send_eod_summary(self) -> None:
        account = self.broker.account_summary()
        with session_scope() as session:
            daily = get_or_create_daily_pnl(session, utcnow().date(), account.balance)
            snap_peak = peak_nav(session, fallback=account.nav)
            peak = max(snap_peak, account.nav)
            dd = (peak - account.nav) / peak if peak else 0.0
            self.slack.eod(
                day=str(utcnow().date()),
                starting_balance=float(daily.starting_balance),
                ending_nav=account.nav,
                realized_pl=float(daily.realized_pl) + float(account.realized_pl) * 0,
                unrealized_pl=account.unrealized_pl,
                trades_opened=daily.trades_opened,
                trades_closed=daily.trades_closed,
                drawdown_pct=dd,
            )
            # Realized for the day from closed local trades is more accurate.
            from src.data.storage import closed_realized_today

            daily.realized_pl = closed_realized_today(session, utcnow().date())
            digest = daily_lesson_digest(session, self.settings)
            try:
                self.slack.warning("Daily lessons", digest)
            except Exception:
                logger.exception("Slack daily lessons failed")

    def send_morning_brief(self, *, force: bool = False) -> dict[str, Any]:
        now = utcnow()
        if now.weekday() >= 5 and not force:
            return {"ok": False, "error": "Weekend — EUR/USD desk briefs Mon–Fri"}
        key = self.settings.tavily_api_key.get_secret_value()
        bundle = self.news.refresh(tavily_key=key, force=True)
        quote = self._quotes.get("EUR/USD")
        with session_scope() as session:
            existing = get_desk_note(session, now.date(), "morning")
            if existing is not None and not force:
                return {"ok": True, "id": existing.id, "kind": "morning", "skipped": "already written"}
            payload = build_morning_brief(
                session=session,
                bundle=bundle,
                settings=self.settings,
                day=now.date(),
                quote_mid=quote.mid if quote else None,
                history=self._history,
            )
            note = upsert_desk_note(session, payload)
            try:
                self.slack.desk_note(note, session=session)
            except Exception:
                logger.exception("Slack morning brief failed")
            logger.info("Morning EUR/USD brief saved ({})", note.sentiment)
            return {"ok": True, "id": note.id, "kind": "morning", "sentiment": note.sentiment}

    def send_night_recap(self, *, force: bool = False) -> dict[str, Any]:
        now = utcnow()
        if now.weekday() >= 5 and not force:
            return {"ok": False, "error": "Weekend — EUR/USD recaps Mon–Fri"}
        account = None
        try:
            account = self.broker.account_summary()
            self._account = account
        except Exception as exc:
            logger.warning("Account unavailable for recap: {}", exc)
        with session_scope() as session:
            existing = get_desk_note(session, now.date(), "recap")
            if existing is not None and not force:
                return {"ok": True, "id": existing.id, "kind": "recap", "skipped": "already written"}
            from src.data.storage import closed_realized_today

            if account is not None:
                daily = get_or_create_daily_pnl(session, now.date(), account.balance)
                daily.realized_pl = closed_realized_today(session, now.date())
            payload = build_night_recap(
                session=session,
                settings=self.settings,
                day=now.date(),
                ending_nav=account.nav if account else None,
                unrealized_pl=account.unrealized_pl if account else 0.0,
            )
            note = upsert_desk_note(session, payload)
            try:
                self.slack.desk_note(note, session=session)
            except Exception:
                logger.exception("Slack night recap failed")
            logger.info("Night EUR/USD recap saved ({})", note.verdict)
            return {
                "ok": True,
                "id": note.id,
                "kind": "recap",
                "verdict": note.verdict,
                "realized_pl": float(note.realized_pl or 0),
            }

    def _maybe_catchup_desk_notes(self) -> None:
        now = utcnow()
        news_due = (now.hour, now.minute) >= (
            self.settings.news_scan_hour,
            self.settings.news_scan_minute,
        )
        if news_due:
            try:
                self.run_news_scan(force=False, deep=True)
            except Exception:
                logger.exception("News scan catch-up failed")
        if now.weekday() >= 5:
            return
        brief_due = (now.hour, now.minute) >= (
            self.settings.briefing_hour,
            self.settings.briefing_minute,
        )
        recap_due = (now.hour, now.minute) >= (self.settings.recap_hour, self.settings.recap_minute)
        with session_scope() as session:
            have_am = get_desk_note(session, now.date(), "morning") is not None
            have_pm = get_desk_note(session, now.date(), "recap") is not None
        if brief_due and not have_am:
            self.send_morning_brief()
        if recap_due and not have_pm:
            self.send_night_recap()

    def chart_pack(self, timeframe: str = "M5", limit: int = 240) -> dict[str, Any]:
        quote = self._quotes.get("EUR/USD")
        try:
            bundle = self.news.refresh(tavily_key=self.settings.tavily_api_key.get_secret_value())
        except Exception:
            bundle = getattr(self.news, "_bundle", None)
        with session_scope() as session:
            return build_chart_pack(
                session,
                symbol="EUR/USD",
                timeframe=timeframe,
                settings=self.settings,
                news=bundle,
                last_price=quote.mid if quote else None,
                limit=limit,
            )

    def dashboard_state(self) -> dict[str, Any]:
        from src.analysis.sampling import sampling_policy
        from src.analysis.decision_health import decision_health
        from src.analysis.indicator_audit import read_status as read_indicator_audit
        from src.analysis.strategy_lab_job import read_learning_status as read_strategy_status
        with session_scope() as session:
            from src.data.storage import (
                get_recent_notifications,
                get_recent_signals,
                get_recent_trades,
                latest_bar,
                latest_snapshot,
            )

            snap = latest_snapshot(session)
            run = latest_pipeline_run(session)
            live = self._account
            if live is not None:
                hist_peak = float(snap.peak_nav) if snap else live.nav
                peak = max(hist_peak, live.nav)
                dd = (peak - live.nav) / peak if peak else 0.0
                account_payload = {
                    "balance": live.balance,
                    "nav": live.nav,
                    "unrealized_pl": live.unrealized_pl,
                    "realized_pl": live.realized_pl,
                    "margin_used": live.margin_used,
                    "margin_available": live.margin_available,
                    "open_trade_count": live.open_trade_count,
                    "peak_nav": peak,
                    "drawdown_pct": dd,
                    "ts": utcnow().isoformat(),
                }
            elif snap is None:
                account_payload = None
            else:
                account_payload = {
                    "balance": float(snap.balance),
                    "nav": float(snap.nav),
                    "unrealized_pl": float(snap.unrealized_pl),
                    "realized_pl": float(snap.realized_pl),
                    "margin_used": float(snap.margin_used),
                    "margin_available": float(snap.margin_available),
                    "open_trade_count": snap.open_trade_count,
                    "peak_nav": float(snap.peak_nav),
                    "drawdown_pct": snap.drawdown_pct,
                    "ts": snap.ts.isoformat(),
                }

            quotes = self.fetcher.quote_enrichment(self._quotes) if self._quotes else []
            if not quotes:
                quotes = []
                for symbol in self.settings.symbols:
                    latest = latest_bar(session, symbol, "M1")
                    ref = self.fetcher.reference_mids.get(symbol)
                    quotes.append(
                        {
                            "symbol": symbol,
                            "bid": None,
                            "ask": None,
                            "mid": float(latest.close) if latest else None,
                            "spread": None,
                            "tradeable": None,
                            "ts": latest.ts.isoformat() if latest else None,
                            "source": "db" if latest else None,
                            "reference_mid": ref,
                            "reference_source": "currencyfreaks" if ref is not None else None,
                            "divergence_pips": None,
                        }
                    )
            return {
                "order_value_cap_fraction": self.settings.max_order_notional_pct,
                "indicator_audit": read_indicator_audit(),
                "strategy_learning": read_strategy_status(),
                "sampling_policy": sampling_policy(self.settings),
                "decision_health": decision_health(session, utcnow()),
                "bot": {
                    "name": "Forex Sentinel",
                    "version": __version__,
                    "specialist": "EUR/USD",
                    "trading_enabled": self.trading_enabled,
                    "strategy_research_only": self.settings.strategy_research_only,
                    "confirmed_entry_policy": self.settings.confirmed_entry_policy,
                    "daily_loss_halt_enabled": (self.settings.oanda_environment != "practice" or self.settings.practice_daily_loss_halt_enabled),
                    "contextual_loss_review": self.settings.oanda_environment == "practice" and self.settings.practice_contextual_loss_review,
                    "environment": self.settings.oanda_environment,
                    "account_id": self.settings.oanda_account_id or self.broker.client._account_id,
                    "signal_timeframe": self.settings.signal_timeframe,
                    "entry_hours": "Broker market hours" if broker_market_hours(self.settings) else "Configured desk calendar",
                    "watchlist": self.settings.symbols,
                    "slack_enabled": self.settings.slack_enabled,
                    "slack_channel": self.slack.target_label,
                    "slack_ready": self.slack._ready,
                    "slack_error": None if self.slack._ready else "no Slack bot token or webhook — connect on Overview",
                    "sheets_configured": bool(self.settings.composio_api_key.get_secret_value()),
                    "sheets_url": (self.settings.google_sheets_spreadsheet_url or "").strip(),
                    "mt4": self.mt4.status().as_dict(),
                    "warm": self._warm,
                    "history_studying": self._history_studying,
                    "briefing": f"{self.settings.briefing_hour:02d}:{self.settings.briefing_minute:02d} UTC Mon–Fri",
                    "news_scan": f"{self.settings.news_scan_hour:02d}:{self.settings.news_scan_minute:02d} UTC daily",
                    "recap": f"{self.settings.recap_hour:02d}:{self.settings.recap_minute:02d} UTC Mon–Fri",
                    "feeds": {
                        "candles": ["oanda", "twelvedata"],
                        "quotes": ["oanda", "currencyfreaks"],
                        "reference_as_of": (
                            self.fetcher.reference_as_of.isoformat()
                            if self.fetcher.reference_as_of
                            else None
                        ),
                    },
                },
                "account": account_payload,
                "quotes": quotes,
                "signals": [
                    {
                        "id": s.id,
                        "ts": s.ts.isoformat(),
                        "symbol": s.symbol,
                        "timeframe": s.timeframe,
                        "action": s.action,
                        "price": s.price,
                        "entry": s.entry,
                        "stop_loss": s.stop_loss,
                        "take_profit_1": s.take_profit_1,
                        "take_profit_2": s.take_profit_2,
                        "risk_reward": s.risk_reward,
                        "strength": s.strength,
                        "confluence": s.confluence,
                        "reason": s.reason,
                        "skipped": s.skipped,
                        "skip_reason": s.skip_reason,
                        "source": getattr(s, "source", None) or "live",
                    }
                    for s in get_recent_signals(session, 40, source="live")
                ],
                "trades": [_trade_dict(t) for t in get_recent_trades(session, 40)],
                "positions": [_trade_dict(t) for t in get_open_trades(session)],
                "notifications": [
                    {
                        "id": n.id,
                        "ts": n.ts.isoformat(),
                        "kind": n.kind,
                        "title": n.title,
                        "delivered": n.delivered,
                        "error": n.error,
                    }
                    for n in get_recent_notifications(session, 20)
                ],
                "pipeline": None
                if run is None
                else {
                    "id": run.id,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "status": run.status,
                    "symbols_processed": run.symbols_processed,
                    "signals_emitted": run.signals_emitted,
                    "orders_placed": run.orders_placed,
                    "error": run.error,
                },
                "last_cycle": self._last_cycle,
                "journals": [_journal_dict(j) for j in get_recent_journals(session, 12)],
                "tape": [_tape_dict(n) for n in get_recent_tape_notes(session, 12)],
                "lessons": [_lesson_dict(r) for r in get_active_learned_rules(session) if r.action in {"skip", "require_high_strength", "prefer"}][:12],
                "desk_notes": [_desk_note_dict(n) for n in get_recent_desk_notes(session, 8)],
                "intel": None if self._intel is None else self._intel.as_dict(),
                "growth": None if self._growth is None else self._growth.as_dict(),
                "history": None if self._history is None else self._history.as_dict(),
                "sheets": self.sheets.status(),
                "mt4": self.mt4.status().as_dict(),
                "news": _news_state(session),
            }

    def set_trading(self, enabled: bool) -> None:
        with self._lock:
            if enabled:
                if getattr(self.settings, "strategy_research_only", False):
                    raise ValueError("Strategy research-only: validation and forward review required before enabling new orders")
                if not self.settings.enable_trading:
                    raise ValueError("ENABLE_TRADING is disabled in configuration")
                self.broker.client.assert_writes_allowed()
                account = self.broker.account_summary()
                self._sync_open_trades(account)
            self.trading_enabled = enabled
        logger.info("Dashboard set ENABLE_TRADING={}", enabled)

    def close_local_trade(self, trade_id: int) -> dict[str, Any]:
        with self._lock:
            return self._close_local_trade_locked(trade_id)

    def _close_local_trade_locked(self, trade_id: int) -> dict[str, Any]:
        with session_scope() as session:
            trade = session.get(Trade, trade_id)
            if trade is None:
                raise KeyError(f"trade {trade_id} not found")
            if trade.status not in {"open", "partial"}:
                return {"ok": False, "error": f"trade is {trade.status}"}
            if not trade.broker_trade_id:
                return {"ok": False, "error": "No broker ticket; cannot confirm a close"}
            payload = self._exec_broker(trade).close_trade(str(trade.broker_trade_id), units="ALL")
            exit_price, realized = self._exec_broker(trade).realized_pl_from_close(payload)
            trade.status = "closed"
            trade.closed_at = utcnow()
            trade.remaining_units = 0
            exit_price, realized, reason = self._resolve_close(trade, exit_price, realized)
            trade.exit_price = exit_price
            trade.realized_pl = realized
            trade.close_reason = "manual"
            journal = record_exit(
                session,
                trade,
                exit_price=exit_price,
                realized_pl=realized,
                close_reason="manual",
                settings=self.settings,
            )
            try:
                self.slack.postmortem(journal, session=session)
            except Exception:
                logger.exception("Slack post-mortem failed")
            self._ingest_journal_into_playbook(journal)
            try:
                self._mirror_mt4_close(session, trade, units="ALL")
            except Exception:
                logger.exception("MT4 copy close after manual flatten failed")
            return {"ok": True, "exit_price": exit_price, "realized_pl": float(trade.realized_pl)}


def _trade_dict(t: Trade) -> dict[str, Any]:
    return {
        "id": t.id,
        "broker_order_id": t.broker_order_id,
        "broker_trade_id": t.broker_trade_id,
        "symbol": t.symbol,
        "side": t.side,
        "units": t.units,
        "remaining_units": t.remaining_units,
        "requested_entry": t.requested_entry,
        "fill_price": t.fill_price,
        "slippage_pips": t.slippage_pips,
        "stop_loss": t.stop_loss,
        "take_profit_1": t.take_profit_1,
        "take_profit_2": t.take_profit_2,
        "status": t.status,
        "tp1_filled": t.tp1_filled,
        "exit_price": t.exit_price,
        "realized_pl": float(t.realized_pl or 0),
        "close_reason": t.close_reason,
        "error_message": t.error_message,
        "source": getattr(t, "source", None) or SOURCE_BOT,
        "venue": getattr(t, "venue", None) or "oanda",
        "opened_at": t.opened_at.isoformat() if t.opened_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
    }


def _journal_dict(j) -> dict[str, Any]:
    return {
        "id": j.id,
        "trade_id": j.trade_id,
        "symbol": j.symbol,
        "side": j.side,
        "fingerprint": j.fingerprint,
        "outcome": j.outcome,
        "entry_thesis": j.entry_thesis,
        "what_went_wrong": j.what_went_wrong,
        "how_to_avoid": j.how_to_avoid,
        "what_went_right": j.what_went_right,
        "lesson": j.lesson,
        "realized_pl": float(j.realized_pl or 0),
        "close_reason": j.close_reason,
        "mistakes": list(getattr(j, "mistakes", None) or []),
        "updated_at": j.updated_at.isoformat() if j.updated_at else None,
    }


def _tape_dict(n) -> dict[str, Any]:
    return {
        "id": n.id,
        "ts": n.ts.isoformat() if n.ts else None,
        "symbol": n.symbol,
        "timeframe": n.timeframe,
        "action": n.action,
        "price": n.price,
        "strength": n.strength,
        "reason": n.reason,
        "body": n.body,
        "skip_reason": n.skip_reason,
        "indicators": n.indicators,
        "posted": n.posted,
    }


def _lesson_dict(r) -> dict[str, Any]:
    return {
        "id": r.id,
        "fingerprint": r.fingerprint,
        "symbol": r.symbol,
        "side": r.side,
        "action": r.action,
        "loss_count": r.loss_count,
        "win_count": r.win_count,
        "net_pl": float(r.net_pl or 0),
        "min_strength": r.min_strength,
        "skip_until": r.skip_until.isoformat() if r.skip_until else None,
        "lesson": r.lesson,
    }


def _desk_note_dict(n) -> dict[str, Any]:
    return {
        "id": n.id,
        "day": n.day.isoformat() if n.day else None,
        "kind": n.kind,
        "sentiment": n.sentiment,
        "looking_for": n.looking_for,
        "goals": n.goals,
        "what_went_right": n.what_went_right,
        "what_went_wrong": n.what_went_wrong,
        "verdict": n.verdict,
        "why": n.why,
        "learned": n.learned,
        "body": n.body,
        "news": n.news,
        "technical": n.technical,
        "realized_pl": float(n.realized_pl or 0),
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


def _news_state(session) -> dict[str, Any]:
    from src.analysis.news_patterns import pattern_rows, recent_news

    patterns = pattern_rows(session)
    items = recent_news(session, 16)
    pending = sum(int(p.get("pending") or 0) for p in patterns)
    stored = sum(int(p.get("samples") or 0) for p in patterns)
    return {
        "stored": stored,
        "pending": pending,
        "patterns": patterns[:14],
        "items": items,
    }


_PIPELINE: TradingPipeline | None = None
_PIPELINE_LOCK = threading.Lock()


def get_pipeline() -> TradingPipeline:
    global _PIPELINE
    with _PIPELINE_LOCK:
        if _PIPELINE is None:
            _PIPELINE = TradingPipeline()
        return _PIPELINE
