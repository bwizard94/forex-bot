"""MetaTrader 4 demo venue — a second book beside OANDA practice.

This cloud process cannot run the Windows MT4 terminal. EUR/USD copies
go out through, in order:

1. MetaApi cloud (if ``METAAPI_TOKEN`` is set) — a hosted MT4 terminal.
2. The bundled Expert Advisor (``mt4/ForexSentinelBridge.mq4``) polling
   ``/api/mt4/bridge``.
3. A local demo ledger using the OANDA mid so the dual book is visible
   until (1) or (2) is live. Ledger fills are labeled ``ledger-…`` and
   are not on MetaQuotes.

Operator tickets stay hands-off. Desk copies use magic ``212100`` and
never flatten a human MT4 fill.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import requests
from loguru import logger

from src.config import Settings, get_settings, reload_settings, upsert_env_values
from src.execution.paper_broker import BrokerError, ExecutionReport
from src.utils import pip_size, price_to_pips, utcnow

VENUE = "mt4"
MAGIC = 212100
MT4_SYMBOL = "EURUSD"
PROVISIONING = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"
CLIENT_API = "https://mt-client-api-v1.{region}.agiliumtrade.ai"


def units_to_lots(units: int) -> float:
    """OANDA units → MT4 lots. 100_000 units = 1.00 lot. Floor 0.01."""
    lots = abs(int(units or 0)) / 100_000.0
    return max(0.01, round(lots, 2))


def lots_to_units(lots: float) -> int:
    return max(1, int(round(float(lots) * 100_000)))


def mt4_symbol(symbol: str) -> str:
    return (symbol or "EUR/USD").replace("/", "").replace("_", "").upper() or MT4_SYMBOL


def realized_pl_usd(*, side: str, fill: float, exit_price: float, units: int) -> float:
    """USD P/L for a EUR/USD ticket (quote is USD)."""
    signed = abs(int(units or 0))
    if side.upper() == "SELL":
        return (float(fill) - float(exit_price)) * signed
    return (float(exit_price) - float(fill)) * signed


@dataclass
class MT4Status:
    enabled: bool
    credentials: bool
    mode: str
    login: str
    server: str
    magic: int
    metaapi_account_id: str
    last_heartbeat: str | None
    heartbeat_age_s: float | None
    error: str | None
    detail: str
    open_count: int = 0
    balance: float | None = None
    equity: float | None = None
    bridge_secret_set: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "credentials": self.credentials,
            "mode": self.mode,
            "login": self.login,
            "server": self.server,
            "magic": self.magic,
            "metaapi_account_id": self.metaapi_account_id,
            "last_heartbeat": self.last_heartbeat,
            "heartbeat_age_s": self.heartbeat_age_s,
            "error": self.error,
            "detail": self.detail,
            "open_count": self.open_count,
            "balance": self.balance,
            "equity": self.equity,
            "bridge_secret_set": self.bridge_secret_set,
            "venue": VENUE,
        }


@dataclass
class MT4Broker:
    settings: Settings
    _last_heartbeat: datetime | None = None
    _last_open: list[dict[str, Any]] = field(default_factory=list)
    _last_balance: float | None = None
    _last_equity: float | None = None
    _last_error: str | None = None
    _mode_override: str | None = None

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._last_heartbeat = None
        self._last_open = []
        self._last_balance = None
        self._last_equity = None
        self._last_error = None
        self._mode_override = None

    @property
    def magic(self) -> int:
        return int(getattr(self.settings, "mt4_magic", MAGIC) or MAGIC)

    @property
    def credentials_ready(self) -> bool:
        login = (self.settings.mt4_login or "").strip()
        password = self.settings.mt4_password.get_secret_value() if self.settings.mt4_password else ""
        server = (self.settings.mt4_server or "").strip()
        return bool(login and password and server)

    @property
    def metaapi_ready(self) -> bool:
        token = self.settings.metaapi_token.get_secret_value() if self.settings.metaapi_token else ""
        account = (self.settings.metaapi_account_id or "").strip()
        return bool(token and account)

    def mode(self) -> str:
        if self._mode_override:
            return self._mode_override
        if not self.settings.mt4_enabled:
            return "off"
        if not self.credentials_ready:
            return "disconnected"
        if self.metaapi_ready:
            return "metaapi"
        if self._heartbeat_fresh():
            return "bridge"
        return "ledger"

    def _heartbeat_fresh(self, *, seconds: float = 180.0) -> bool:
        if self._last_heartbeat is None:
            return False
        age = (utcnow() - self._last_heartbeat).total_seconds()
        return age <= seconds

    def status(self) -> MT4Status:
        login = (self.settings.mt4_login or "").strip()
        server = (self.settings.mt4_server or "").strip()
        mode = self.mode()
        age = None
        hb = None
        if self._last_heartbeat is not None:
            age = round((utcnow() - self._last_heartbeat).total_seconds(), 1)
            hb = self._last_heartbeat.isoformat()
        details = {
            "off": "MT4 mirroring is paused (MT4_ENABLED=false).",
            "disconnected": "Paste MT4 demo login, password, and server on Overview.",
            "ledger": (
                "Credentials saved. Copies are booked on a local MT4 ledger until "
                "the Expert Advisor heartbeats or a MetaApi token is connected."
            ),
            "bridge": "Expert Advisor is live — new EUR/USD tickets go to the MT4 demo.",
            "metaapi": "MetaApi cloud terminal is connected — new EUR/USD tickets go to MT4.",
        }
        secret = self.settings.mt4_bridge_secret.get_secret_value() if self.settings.mt4_bridge_secret else ""
        return MT4Status(
            enabled=bool(self.settings.mt4_enabled),
            credentials=self.credentials_ready,
            mode=mode,
            login=login,
            server=server,
            magic=self.magic,
            metaapi_account_id=(self.settings.metaapi_account_id or "").strip(),
            last_heartbeat=hb,
            heartbeat_age_s=age,
            error=self._last_error,
            detail=details.get(mode, mode),
            open_count=len(self._last_open),
            balance=self._last_balance,
            equity=self._last_equity,
            bridge_secret_set=bool(secret),
        )

    def connect(
        self,
        *,
        login: str,
        password: str,
        server: str,
        metaapi_token: str = "",
        enabled: bool = True,
    ) -> dict[str, Any]:
        login = (login or "").strip()
        password = (password or "").strip()
        server = (server or "").strip()
        token = (metaapi_token or "").strip()
        if not login or not password or not server:
            return {
                "ok": False,
                "error": "MT4 demo login, password, and server are all required.",
            }
        updates = {
            "MT4_ENABLED": "true" if enabled else "false",
            "MT4_LOGIN": login,
            "MT4_PASSWORD": password,
            "MT4_SERVER": server,
        }
        existing_secret = self.settings.mt4_bridge_secret.get_secret_value() if self.settings.mt4_bridge_secret else ""
        new_secret = None
        if not existing_secret:
            new_secret = secrets.token_urlsafe(18)
            updates["MT4_BRIDGE_SECRET"] = new_secret
        if token:
            updates["METAAPI_TOKEN"] = token
        upsert_env_values(updates)
        self.settings = reload_settings()
        self._last_error = None
        if token:
            try:
                provisioned = self._provision_metaapi()
                if not provisioned.get("ok"):
                    self._last_error = str(provisioned.get("error") or "MetaApi provision failed")
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                logger.warning("MetaApi provision failed: {}", exc)
        out = {"ok": True, **self.status().as_dict()}
        if new_secret:
            out["bridge_secret"] = new_secret
            out["detail"] = (
                (out.get("detail") or "")
                + " Copy the bridge secret into mt4/ForexSentinelBridge.mq4 (shown once)."
            )
        return out

    def _headers(self) -> dict[str, str]:
        token = self.settings.metaapi_token.get_secret_value()
        return {"auth-token": token, "Content-Type": "application/json"}

    def _client_root(self) -> str:
        region = (self.settings.metaapi_region or "new-york").strip() or "new-york"
        return CLIENT_API.format(region=region)

    def _provision_metaapi(self) -> dict[str, Any]:
        token = self.settings.metaapi_token.get_secret_value()
        if not token:
            return {"ok": False, "error": "no MetaApi token"}
        existing = (self.settings.metaapi_account_id or "").strip()
        if existing:
            try:
                resp = requests.get(
                    f"{PROVISIONING}/users/current/accounts/{existing}",
                    headers=self._headers(),
                    timeout=20,
                )
                if resp.status_code < 400:
                    return {"ok": True, "id": existing, "raw": resp.json()}
            except Exception as exc:  # noqa: BLE001
                logger.warning("MetaApi account lookup failed: {}", exc)
        body = {
            "name": "Forex Sentinel EURUSD",
            "login": (self.settings.mt4_login or "").strip(),
            "password": self.settings.mt4_password.get_secret_value(),
            "server": (self.settings.mt4_server or "").strip(),
            "platform": "mt4",
            "magic": self.magic,
            "region": (self.settings.metaapi_region or "new-york").strip() or "new-york",
        }
        resp = requests.post(
            f"{PROVISIONING}/users/current/accounts",
            headers=self._headers(),
            json=body,
            timeout=30,
        )
        if resp.status_code >= 400:
            return {"ok": False, "error": f"MetaApi {resp.status_code}: {resp.text[:240]}"}
        payload = resp.json() if resp.content else {}
        account_id = str(payload.get("id") or payload.get("_id") or "")
        if not account_id:
            return {"ok": False, "error": "MetaApi did not return an account id", "raw": payload}
        upsert_env_values({"METAAPI_ACCOUNT_ID": account_id})
        self.settings = reload_settings()
        logger.info("MetaApi MT4 account {} provisioned ({})", account_id, payload.get("state"))
        return {"ok": True, "id": account_id, "raw": payload}

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
        if not self.settings.mt4_enabled or not self.credentials_ready:
            return ExecutionReport(
                ok=False,
                broker_order_id=None,
                broker_trade_id=None,
                fill_price=None,
                units=units,
                slippage_pips=None,
                raw={},
                error="MT4 demo is not connected",
            )
        lots = units_to_lots(units)
        comment = (comment or f"{side} EURUSD")[:31]
        mode = self.mode()
        if mode == "metaapi":
            report = self._metaapi_market(
                side=side,
                lots=lots,
                stop_loss=stop_loss,
                take_profit=take_profit,
                requested_entry=requested_entry,
                comment=comment,
            )
            if report.ok:
                return report
            logger.warning("MetaApi order failed ({}) — falling through to ledger", report.error)
        if mode == "bridge":
            return self._enqueue(
                action="open",
                side=side,
                units=units,
                lots=lots,
                stop_loss=stop_loss,
                take_profit=take_profit,
                requested_entry=requested_entry,
                comment=comment,
            )
        return self._ledger_fill(
            side=side,
            units=units,
            lots=lots,
            stop_loss=stop_loss,
            take_profit=take_profit,
            requested_entry=requested_entry,
            comment=comment,
        )

    def _metaapi_market(
        self,
        *,
        side: str,
        lots: float,
        stop_loss: float,
        take_profit: float,
        requested_entry: float,
        comment: str,
    ) -> ExecutionReport:
        account = (self.settings.metaapi_account_id or "").strip()
        action = "ORDER_TYPE_BUY" if side.upper() == "BUY" else "ORDER_TYPE_SELL"
        body: dict[str, Any] = {
            "actionType": action,
            "symbol": MT4_SYMBOL,
            "volume": lots,
            "comment": comment,
            "clientId": f"fs-{utcnow().strftime('%H%M%S')}-{side[:1]}",
        }
        if stop_loss:
            body["stopLoss"] = round(float(stop_loss), 5)
        if take_profit:
            body["takeProfit"] = round(float(take_profit), 5)
        try:
            resp = requests.post(
                f"{self._client_root()}/users/current/accounts/{account}/trade",
                headers=self._headers(),
                json=body,
                timeout=25,
            )
            payload = resp.json() if resp.content else {}
            if resp.status_code >= 400:
                return ExecutionReport(
                    ok=False,
                    broker_order_id=None,
                    broker_trade_id=None,
                    fill_price=None,
                    units=lots_to_units(lots),
                    slippage_pips=None,
                    raw=payload,
                    error=f"MetaApi trade {resp.status_code}: {str(payload)[:240]}",
                )
        except Exception as exc:  # noqa: BLE001
            return ExecutionReport(
                ok=False,
                broker_order_id=None,
                broker_trade_id=None,
                fill_price=None,
                units=lots_to_units(lots),
                slippage_pips=None,
                raw={"error": str(exc)},
                error=str(exc),
            )
        numeric = payload.get("numericCode")
        if numeric not in (None, 0, "0"):
            return ExecutionReport(
                ok=False,
                broker_order_id=str(payload.get("orderId") or "") or None,
                broker_trade_id=None,
                fill_price=None,
                units=lots_to_units(lots),
                slippage_pips=None,
                raw=payload,
                error=str(payload.get("stringCode") or payload.get("message") or payload),
            )
        fill = payload.get("orderFillPrice") or payload.get("price") or requested_entry
        try:
            fill_px = float(fill)
        except (TypeError, ValueError):
            fill_px = float(requested_entry)
        ticket = str(payload.get("positionId") or payload.get("orderId") or payload.get("ticket") or "")
        slip = price_to_pips("EUR/USD", abs(fill_px - float(requested_entry))) if requested_entry else None
        return ExecutionReport(
            ok=True,
            broker_order_id=str(payload.get("orderId") or ticket) or None,
            broker_trade_id=ticket or None,
            fill_price=fill_px,
            units=lots_to_units(lots),
            slippage_pips=slip,
            raw=payload,
            stop_loss=float(stop_loss or 0) or None,
            take_profit=float(take_profit or 0) or None,
        )

    def _ledger_fill(
        self,
        *,
        side: str,
        units: int,
        lots: float,
        stop_loss: float,
        take_profit: float,
        requested_entry: float,
        comment: str,
    ) -> ExecutionReport:
        ticket = f"ledger-{uuid4().hex[:12]}"
        logger.info(
            "MT4 local ledger {} EURUSD lots={} ticket={} (not on MetaQuotes yet)",
            side,
            lots,
            ticket,
        )
        return ExecutionReport(
            ok=True,
            broker_order_id=ticket,
            broker_trade_id=ticket,
            fill_price=float(requested_entry),
            units=int(units),
            slippage_pips=0.0,
            raw={"mode": "ledger", "lots": lots, "comment": comment, "magic": self.magic},
            stop_loss=float(stop_loss or 0) or None,
            take_profit=float(take_profit or 0) or None,
        )

    def _enqueue(
        self,
        *,
        action: str,
        side: str,
        units: int,
        lots: float,
        stop_loss: float,
        take_profit: float,
        requested_entry: float,
        comment: str,
        ticket: str = "",
    ) -> ExecutionReport:
        from src.data.storage import insert_mt4_command, session_scope

        with session_scope() as session:
            row = insert_mt4_command(
                session,
                {
                    "action": action,
                    "symbol": MT4_SYMBOL,
                    "side": side.upper(),
                    "lots": lots,
                    "units": int(units),
                    "stop_loss": float(stop_loss or 0),
                    "take_profit": float(take_profit or 0),
                    "magic": self.magic,
                    "comment": comment,
                    "ticket": ticket or None,
                    "status": "pending",
                    "requested_entry": float(requested_entry or 0),
                },
            )
            cmd_id = row.id
        pending = f"pending-{cmd_id}"
        logger.info("Queued MT4 {} {} lots={} as {}", action, side, lots, pending)
        return ExecutionReport(
            ok=True,
            broker_order_id=str(cmd_id),
            broker_trade_id=pending,
            fill_price=float(requested_entry),
            units=int(units),
            slippage_pips=0.0,
            raw={"mode": "bridge", "command_id": cmd_id, "lots": lots},
            stop_loss=float(stop_loss or 0) or None,
            take_profit=float(take_profit or 0) or None,
        )

    def close_trade(self, broker_trade_id: str, units: str = "ALL") -> dict[str, Any]:
        ticket = str(broker_trade_id or "")
        if ticket.startswith("ledger-") or ticket.startswith("pending-"):
            return {"orderFillTransaction": {"price": None, "pl": None, "reason": "local_mt4"}}
        mode = self.mode()
        if mode == "metaapi":
            try:
                body: dict[str, Any] = {"actionType": "POSITION_CLOSE_ID", "positionId": ticket}
                if units and units != "ALL":
                    try:
                        body["volume"] = units_to_lots(int(float(units)))
                    except (TypeError, ValueError):
                        pass
                resp = requests.post(
                    f"{self._client_root()}/users/current/accounts/{self.settings.metaapi_account_id}/trade",
                    headers=self._headers(),
                    json=body,
                    timeout=20,
                )
                payload = resp.json() if resp.content else {}
                if resp.status_code >= 400:
                    raise BrokerError(f"MetaApi close {resp.status_code}: {payload}")
                price = payload.get("orderFillPrice") or payload.get("price")
                return {"orderFillTransaction": {"price": price, "pl": payload.get("profit")}}
            except BrokerError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise BrokerError(f"Failed to close MT4 {ticket}: {exc}") from exc
        lots = 0.0
        if units and units != "ALL":
            try:
                lots = units_to_lots(int(float(units)))
            except (TypeError, ValueError):
                lots = 0.0
        self._enqueue(
            action="close",
            side="SELL",
            units=int(float(units)) if units not in {"", "ALL"} else 0,
            lots=lots,
            stop_loss=0.0,
            take_profit=0.0,
            requested_entry=0.0,
            comment="close",
            ticket=ticket,
        )
        return {"orderFillTransaction": {"price": None, "pl": None, "reason": "queued_mt4"}}

    def modify_trade(
        self,
        broker_trade_id: str,
        *,
        symbol: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> dict[str, Any]:
        ticket = str(broker_trade_id or "")
        if ticket.startswith("ledger-") or ticket.startswith("pending-"):
            return {"ok": True, "mode": "ledger"}
        if self.mode() == "metaapi":
            body: dict[str, Any] = {
                "actionType": "POSITION_MODIFY",
                "positionId": ticket,
            }
            if stop_loss is not None:
                body["stopLoss"] = round(float(stop_loss), 5)
            if take_profit is not None:
                body["takeProfit"] = round(float(take_profit), 5)
            resp = requests.post(
                f"{self._client_root()}/users/current/accounts/{self.settings.metaapi_account_id}/trade",
                headers=self._headers(),
                json=body,
                timeout=20,
            )
            if resp.status_code >= 400:
                raise BrokerError(f"MetaApi modify {resp.status_code}: {resp.text[:240]}")
            return resp.json() if resp.content else {}
        self._enqueue(
            action="modify",
            side="BUY",
            units=0,
            lots=0.0,
            stop_loss=float(stop_loss or 0),
            take_profit=float(take_profit or 0),
            requested_entry=0.0,
            comment="modify",
            ticket=ticket,
        )
        return {"ok": True, "mode": "bridge"}

    def open_trades(self) -> list[dict[str, Any]]:
        if self.mode() == "metaapi":
            try:
                resp = requests.get(
                    f"{self._client_root()}/users/current/accounts/{self.settings.metaapi_account_id}/positions",
                    headers=self._headers(),
                    timeout=20,
                )
                if resp.status_code >= 400:
                    logger.warning("MetaApi positions failed: {}", resp.text[:200])
                    return list(self._last_open)
                rows = resp.json() if resp.content else []
                if isinstance(rows, dict):
                    rows = rows.get("positions") or rows.get("openPositions") or []
                mapped = []
                for row in rows or []:
                    if not isinstance(row, dict):
                        continue
                    magic = int(row.get("magic") or 0)
                    if magic != self.magic:
                        continue
                    mapped.append(self._position_row(row))
                self._last_open = mapped
                return mapped
            except Exception as exc:  # noqa: BLE001
                logger.warning("MetaApi positions error: {}", exc)
                return list(self._last_open)
        return list(self._last_open)

    def _position_row(self, row: dict[str, Any]) -> dict[str, Any]:
        volume = float(row.get("volume") or row.get("lots") or 0)
        side = str(row.get("type") or row.get("side") or "").upper()
        if "SELL" in side or side in {"1", "POSITION_TYPE_SELL"}:
            units = -lots_to_units(abs(volume))
        else:
            units = lots_to_units(abs(volume))
        ticket = str(row.get("id") or row.get("ticket") or row.get("positionId") or "")
        return {
            "id": ticket,
            "instrument": "EUR_USD",
            "currentUnits": units,
            "initialUnits": units,
            "price": float(row.get("openPrice") or row.get("price") or 0),
            "unrealizedPL": float(row.get("unrealizedProfit") or row.get("profit") or 0),
            "stopLossOrder": {"price": row.get("stopLoss")},
            "takeProfitOrder": {"price": row.get("takeProfit")},
            "clientExtensions": {
                "id": f"fs-{ticket}" if int(row.get("magic") or 0) == self.magic else "",
                "tag": "EURUSD",
                "comment": str(row.get("comment") or "EURUSD"),
            },
            "openTime": row.get("time") or row.get("openTime"),
            "magic": int(row.get("magic") or 0),
            "venue": VENUE,
        }

    def realized_pl_from_close(self, payload: dict[str, Any]) -> tuple[float | None, float | None]:
        close_tx = payload.get("orderFillTransaction") or {}
        price = float(close_tx["price"]) if close_tx.get("price") not in (None, "") else None
        pl = float(close_tx["pl"]) if close_tx.get("pl") not in (None, "") else None
        return price, pl

    def pull_commands(self, *, secret: str, limit: int = 8) -> dict[str, Any]:
        if not self._valid_secret(secret):
            return {"ok": False, "error": "bad bridge secret", "commands": []}
        from src.data.storage import list_pending_mt4_commands, session_scope

        with session_scope() as session:
            rows = list_pending_mt4_commands(session, limit=limit)
            out = []
            for row in rows:
                row.status = "sent"
                out.append(
                    {
                        "id": row.id,
                        "action": row.action,
                        "symbol": row.symbol,
                        "side": row.side,
                        "lots": row.lots,
                        "sl": row.stop_loss,
                        "tp": row.take_profit,
                        "magic": row.magic,
                        "comment": row.comment,
                        "ticket": row.ticket,
                    }
                )
        return {"ok": True, "commands": out, "magic": self.magic}

    def apply_bridge(self, payload: dict[str, Any]) -> dict[str, Any]:
        secret = str(payload.get("secret") or "")
        if not self._valid_secret(secret):
            return {"ok": False, "error": "bad bridge secret"}
        self.note_heartbeat(payload.get("heartbeat") or {})
        results = payload.get("results") or []
        applied = 0
        from src.data.storage import Mt4Command, Trade, session_scope
        from sqlalchemy import select

        with session_scope() as session:
            for item in results:
                if not isinstance(item, dict):
                    continue
                cmd_id = item.get("id")
                if cmd_id is None:
                    continue
                row = session.get(Mt4Command, int(cmd_id))
                if row is None:
                    continue
                if item.get("ok"):
                    row.status = "done"
                    row.ticket = str(item.get("ticket") or row.ticket or "")
                    if item.get("fill"):
                        try:
                            row.fill_price = float(item["fill"])
                        except (TypeError, ValueError):
                            pass
                    row.error = None
                    pending = f"pending-{cmd_id}"
                    trade = session.scalar(select(Trade).where(Trade.broker_trade_id == pending))
                    if trade is not None and row.ticket:
                        trade.broker_trade_id = row.ticket
                        trade.broker_order_id = row.ticket
                        if row.fill_price:
                            trade.fill_price = float(row.fill_price)
                else:
                    row.status = "error"
                    row.error = str(item.get("error") or "EA rejected")
                applied += 1
        self._mode_override = "bridge"
        return {"ok": True, "applied": applied, **self.status().as_dict()}

    def note_heartbeat(self, heartbeat: dict[str, Any]) -> None:
        self._last_heartbeat = utcnow()
        self._last_error = None
        if heartbeat.get("balance") is not None:
            try:
                self._last_balance = float(heartbeat["balance"])
            except (TypeError, ValueError):
                pass
        if heartbeat.get("equity") is not None:
            try:
                self._last_equity = float(heartbeat["equity"])
            except (TypeError, ValueError):
                pass
        open_rows = heartbeat.get("open") or []
        mapped = []
        for row in open_rows:
            if not isinstance(row, dict):
                continue
            mapped.append(self._position_row(row))
        if mapped:
            self._last_open = mapped
        self._mode_override = "bridge"

    def _valid_secret(self, secret: str) -> bool:
        expected = self.settings.mt4_bridge_secret.get_secret_value() if self.settings.mt4_bridge_secret else ""
        if not expected or not secret:
            return False
        return secrets.compare_digest(str(secret), expected)
