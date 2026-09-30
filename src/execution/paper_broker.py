"""OANDA v20 practice (paper) broker: open, monitor, modify, and close trades.

Wraps ``oandapyV20`` with reconnection, price-precision rounding, and
lifecycle bookkeeping (fill, slippage, partial TP1, realized P/L).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import math
import time
from uuid import uuid4

import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.positions as positions
import oandapyV20.endpoints.trades as trades
import oandapyV20.endpoints.transactions as transactions
from loguru import logger
from oandapyV20.exceptions import V20Error

from src.config import Settings, get_settings
from src.data.fetcher import OandaClient
from src.execution.trade_guard import classify_remote_trade, SOURCE_BOT
from src.execution.risk_manager import AccountState
from src.utils import format_price, pip_size, price_to_pips, to_display_symbol, to_oanda_instrument, utcnow


class BrokerError(RuntimeError):
    pass


@dataclass(slots=True)
class ExecutionReport:
    ok: bool
    broker_order_id: str | None
    broker_trade_id: str | None
    fill_price: float | None
    units: int
    slippage_pips: float | None
    raw: dict[str, Any]
    error: str | None = None
    stop_loss: float | None = None
    take_profit: float | None = None


class PaperBroker:
    def __init__(self, settings: Settings | None = None, client: OandaClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or OandaClient(self.settings)
        self._precision: dict[str, int] = {}
        self._last_transaction_id: str | None = None
        self._close_retry_after: dict[str, float] = {}

    @property
    def account_id(self) -> str:
        return self.client.account_id

    def _precision_for(self, symbol: str) -> int:
        display = to_display_symbol(symbol)
        if display in self._precision:
            return self._precision[display]
        endpoint = accounts.AccountInstruments(
            accountID=self.account_id,
            params={"instruments": to_oanda_instrument(display)},
        )
        payload = self.client.request(endpoint)
        specs = (payload.get("instruments") or [{}])[0]
        precision = int(specs.get("displayPrecision") or (3 if "JPY" in display else 5))
        self._precision[display] = precision
        return precision

    def _px(self, symbol: str, price: float) -> str:
        return format_price(symbol, price, self._precision_for(symbol))

    def account_summary(self) -> AccountState:
        payload = self.client.request(accounts.AccountSummary(accountID=self.account_id))
        acct = payload.get("account") or {}
        self._last_transaction_id = payload.get("lastTransactionID") or acct.get("lastTransactionID")
        return AccountState(
            balance=float(acct.get("balance") or 0),
            nav=float(acct.get("NAV") or acct.get("balance") or 0),
            unrealized_pl=float(acct.get("unrealizedPL") or 0),
            realized_pl=float(acct.get("pl") or 0),
            margin_used=float(acct.get("marginUsed") or 0),
            margin_available=float(acct.get("marginAvailable") or 0),
            open_trade_count=int(acct.get("openTradeCount") or 0),
            currency=str(acct.get("currency") or "USD"),
            raw=acct,
        )

    def quote_to_usd(self, symbol: str, mid_price: float) -> float:
        """Convert 1 unit of quote currency into USD."""
        display = to_display_symbol(symbol)
        quote = display.split("/")[1]
        if quote == "USD":
            return 1.0
        if display.startswith("USD/"):
            return 1.0 / mid_price if mid_price else 1.0
        # Cross: best-effort via the USD_QUOTE pair when we have mid; caller
        # can pass 1.0. For USD/JPY the branch above applies.
        return 1.0

    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        units: int,
        stop_loss: float,
        take_profit: float,
        requested_entry: float,
        comment: str | None = None,
    ) -> ExecutionReport:
        side = side.upper()
        if side not in {"BUY", "SELL"} or units <= 0:
            raise BrokerError("Invalid order side or quantity")
        if not all(math.isfinite(x) and x > 0 for x in (requested_entry, stop_loss, take_profit)):
            raise BrokerError("Order prices must be finite and positive")
        direction = 1 if side == "BUY" else -1
        distance = direction * (requested_entry - stop_loss)
        if distance + 1e-10 < pip_size(symbol) * max(5.0, self.settings.min_stop_pips):
            raise BrokerError("Stop is on the wrong side or below the minimum distance")
        bound = requested_entry + direction * self.settings.max_fill_slippage_pips * pip_size(symbol)
        if direction * (take_profit - bound) <= 0:
            raise BrokerError("Target does not clear the maximum entry slippage")
        stamp = {"id": f"fs-{uuid4().hex}", "tag": "EURUSD", "comment": str(comment or "Forex Sentinel")[:128]}
        body = {"order": {
            "type": "MARKET", "instrument": to_oanda_instrument(symbol),
            "units": str(direction * abs(int(units))), "timeInForce": "FOK",
            "positionFill": "OPEN_ONLY", "priceBound": self._px(symbol, bound),
            "clientExtensions": stamp, "tradeClientExtensions": dict(stamp),
            "stopLossOnFill": {"price": self._px(symbol, stop_loss), "timeInForce": "GTC"},
            "takeProfitOnFill": {"price": self._px(symbol, take_profit), "timeInForce": "GTC"},
        }}
        try:
            payload = self.client.request(orders.OrderCreate(self.account_id, data=body))
        except V20Error as exc:
            return ExecutionReport(False, None, None, None, 0, None, {}, error=str(exc))
        fill = payload.get("orderFillTransaction") or {}
        opened = fill.get("tradeOpened") or {}
        created = payload.get("orderCreateTransaction") or {}
        if not fill or not opened.get("tradeID") or not fill.get("price"):
            reason = (payload.get("orderCancelTransaction") or payload.get("orderRejectTransaction") or {}).get("reason")
            if not reason:
                self.client.pause_writes("Opening fill not confirmed")
                raise BrokerError("Order response has no confirmed opening fill; reconcile before resubmitting")
            return ExecutionReport(False, str(created.get("id") or "") or None, None, None, 0, None, payload, error=reason)
        try:
            price = float(opened.get("price", fill["price"]))
            actual_units = float(opened["units"])
            if (not math.isfinite(price) or price <= 0
                    or not math.isfinite(actual_units) or not actual_units.is_integer()
                    or abs(actual_units) != units
                    or direction * actual_units <= 0
                    or fill.get("instrument", to_oanda_instrument(symbol)) != to_oanda_instrument(symbol)):
                raise ValueError("Invalid opening fill")
            filled_units = abs(int(actual_units))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            self.client.pause_writes("Opening fill invalid; reconcile broker state")
            raise BrokerError("Opening fill invalid; reconcile broker state") from exc
        return ExecutionReport(
            True, str(created.get("id") or fill.get("orderID") or "") or None,
            str(opened["tradeID"]), price, filled_units,
            direction * (price - requested_entry) / pip_size(symbol), payload,
            stop_loss=float(self._px(symbol, stop_loss)), take_profit=take_profit,
        )

    def _protect_from_fill(
        self,
        *,
        symbol: str,
        side: str,
        fill_price: float,
        requested_entry: float,
        stop_loss: float,
        take_profit: float,
    ) -> tuple[float, float]:
        """Rebuild SL/TP from the actual fill so the stop clears the live spread."""
        entry = requested_entry or fill_price
        sl_dist = abs(entry - stop_loss) if stop_loss else 0.0
        tp_dist = abs(entry - take_profit) if take_profit else sl_dist * 2
        min_sl = pip_size(symbol) * max(5.0, float(self.settings.min_stop_pips))
        sl_dist = max(sl_dist, min_sl)
        if tp_dist < sl_dist * 1.2:
            tp_dist = sl_dist * (self.settings.atr_tp1_multiplier / max(self.settings.atr_sl_multiplier, 0.1))
        if side.upper() == "SELL":
            return fill_price + sl_dist, fill_price - tp_dist
        return fill_price - sl_dist, fill_price + tp_dist

    def open_trades(self) -> list[dict[str, Any]]:
        payload = self.client.request(trades.OpenTrades(self.account_id))
        return list(payload.get("trades") or [])

    def trade_details(self, broker_trade_id: str) -> dict[str, Any]:
        payload = self.client.request(trades.TradeDetails(self.account_id, tradeID=str(broker_trade_id)))
        row = payload.get("trade") or {}
        if str(row.get("id")) != str(broker_trade_id):
            raise BrokerError("Missing or mismatched broker trade details")
        return row

    def _owned_trade(self, broker_trade_id: str) -> dict[str, Any]:
        row = self.trade_details(broker_trade_id)
        if classify_remote_trade(row) != SOURCE_BOT:
            raise BrokerError("Operator/unstamped trade: automatic writes are forbidden")
        if row.get("state") != "OPEN":
            raise BrokerError("Trade is no longer open; reconcile first")
        return row

    def confirmed_close_reason(self, row: dict[str, Any]) -> str:
        """Attribute only the fill that fully closed this ticket, never price proximity."""
        if row.get("state") != "CLOSED":
            return "broker_closed"
        ids = row.get("closingTransactionIDs") or []
        # OANDA IDs increase chronologically; earlier fills can be partial exits.
        for transaction_id in sorted({str(v) for v in ids}, key=int, reverse=True):
            payload = self.client.request(transactions.TransactionDetails(
                self.account_id, transactionID=transaction_id))
            fill = payload.get("transaction") or {}
            if str(fill.get("id")) != transaction_id or fill.get("type") != "ORDER_FILL":
                continue
            if not any(str(t.get("tradeID")) == str(row.get("id"))
                       for t in fill.get("tradesClosed", [])):
                continue
            return {"STOP_LOSS_ORDER": "stop_loss",
                    "GUARANTEED_STOP_LOSS_ORDER": "stop_loss",
                    "TRAILING_STOP_LOSS_ORDER": "stop_loss",
                    "TAKE_PROFIT_ORDER": "take_profit",
                    "MARKET_ORDER_TRADE_CLOSE": "broker_market_close",
                    "MARKET_ORDER_MARGIN_CLOSEOUT": "margin_closeout"}.get(
                        fill.get("reason"), "broker_closed")
        return "broker_closed"

    def close_trade(self, broker_trade_id: str, units: str = "ALL") -> dict[str, Any]:
        if time.monotonic() < self._close_retry_after.get(str(broker_trade_id), 0):
            raise BrokerError("Close is cooling down after a broker rejection")
        row = self._owned_trade(broker_trade_id)
        expected = abs(float(row["currentUnits"])) if units == "ALL" else float(units)
        if not math.isfinite(expected) or expected <= 0 or expected > abs(float(row["currentUnits"])):
            raise BrokerError("Invalid close quantity")
        try:
            payload = self.client.request(trades.TradeClose(self.account_id, tradeID=str(broker_trade_id), data={"units": units}))
        except V20Error as exc:
            self._close_retry_after[str(broker_trade_id)] = time.monotonic() + 300
            raise BrokerError(f"Failed to close trade {broker_trade_id}: {exc}") from exc
        fill = payload.get("orderFillTransaction") or {}
        reductions = list(fill.get("tradesClosed") or []) + ([fill["tradeReduced"]] if fill.get("tradeReduced") else [])
        matched = [r for r in reductions if str(r.get("tradeID")) == str(broker_trade_id)]
        try:
            quantities = [abs(float(r["units"])) for r in matched]
            confirmed = (bool(matched) and len(matched) == len(reductions)
                         and all(math.isfinite(q) and q > 0 for q in quantities)
                         and abs(sum(quantities) - expected) <= 1e-6)
        except (KeyError, TypeError, ValueError, OverflowError):
            confirmed = False
        if not confirmed:
            reason = (payload.get("orderCancelTransaction") or {}).get("reason", "unconfirmed close")
            self._close_retry_after[str(broker_trade_id)] = time.monotonic() + 300
            if not payload.get("orderCancelTransaction"):
                self.client.pause_writes("Close fill not confirmed")
            raise BrokerError(f"Close not confirmed: {reason}")
        try:
            self.realized_pl_from_close(payload)
        except (BrokerError, KeyError, TypeError, ValueError, OverflowError) as exc:
            self.client.pause_writes("Close outcome incomplete; reconcile broker state")
            raise BrokerError("Close outcome incomplete; reconcile broker state") from exc
        return payload

    def modify_trade(
        self,
        broker_trade_id: str,
        *,
        symbol: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> dict[str, Any]:
        self._owned_trade(broker_trade_id)
        body: dict[str, Any] = {}
        if stop_loss is not None:
            body["stopLoss"] = {"price": self._px(symbol, stop_loss), "timeInForce": "GTC"}
        if take_profit is not None:
            body["takeProfit"] = {"price": self._px(symbol, take_profit), "timeInForce": "GTC"}
        if not body:
            return {}
        try:
            payload = self.client.request(trades.TradeCRCDO(self.account_id, tradeID=str(broker_trade_id), data=body))
            for name in body:
                if not payload.get(name + "OrderTransaction") or payload.get(name + "OrderRejectTransaction"):
                    raise BrokerError(f"{name} modification not confirmed")
            return payload
        except V20Error as exc:
            raise BrokerError(f"Failed to modify trade {broker_trade_id}: {exc}") from exc

    def annotate_trade(self, broker_trade_id: str, *, comment: str, tag: str = "EURUSD") -> dict[str, Any]:
        """Stamp the live OANDA demo trade with the desk comment (visible on fxTrade)."""
        self._owned_trade(broker_trade_id)
        data = {
            "clientExtensions": {
                "id": f"fs-{broker_trade_id}",
                "tag": tag[:128],
                "comment": (comment or "")[:128],
            }
        }
        try:
            return self.client.request(
                trades.TradeClientExtensions(self.account_id, tradeID=str(broker_trade_id), data=data)
            )
        except V20Error as exc:
            logger.warning("OANDA trade comment failed for {}: {}", broker_trade_id, exc)
            return {"error": str(exc)}

    def close_position(self, symbol: str) -> dict[str, Any]:
        raise BrokerError("Whole-position closes are disabled; close individually verified bot trades")

    def realized_pl_from_close(self, payload: dict[str, Any]) -> tuple[float | None, float | None]:
        """Extract (exit_price, realized_pl) from a close/partial-close payload."""
        close_tx = (
            payload.get("orderFillTransaction")
            or payload.get("orderFillTransaction".lower())
            or {}
        )
        # TradeClose returns orderFillTransaction with pl / price.
        if not close_tx:
            # Some payloads nest under 'shortOrderFillTransaction' etc.
            for key in (
                "longOrderFillTransaction",
                "shortOrderFillTransaction",
            ):
                if key in payload:
                    close_tx = payload[key]
                    break
        price = float(close_tx["price"]) if close_tx.get("price") else None
        pl = float(close_tx["pl"]) if close_tx.get("pl") is not None else None
        trades_closed = close_tx.get("tradesClosed") or []
        reductions = list(trades_closed) + ([close_tx["tradeReduced"]] if close_tx.get("tradeReduced") else [])
        if pl is None and reductions:
            if any(t.get("realizedPL") is None for t in reductions):
                raise BrokerError("Close response missing realized P/L; zero cannot be assumed")
            pl = sum(float(t["realizedPL"]) for t in reductions)
        if price is None or pl is None or not math.isfinite(price) or not math.isfinite(pl) or price <= 0:
            raise BrokerError("Close response lacks a confirmed fill price and realized P/L")
        return price, pl
