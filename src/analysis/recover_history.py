"""Recover closed EUR/USD practice trades into an isolated research snapshot.

Only GET endpoints are constructed. Never writes the execution database.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import oandapyV20.endpoints.trades as trades
import oandapyV20.endpoints.transactions as transactions

from src.execution.trade_guard import classify_remote_trade


def amount(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite broker amount")
    return str(result)


def recover(client, *, page_size=500, max_pages=100):
    """Complete pagination or fail; never publish a partial recovery as complete."""
    if client.settings.oanda_environment != "practice":
        raise ValueError("History recovery is practice-only")
    if not 1 <= page_size <= 500 or max_pages < 1:
        raise ValueError("Invalid pagination limits")
    account = client.account_id
    records = {}
    before = None
    pages = 0
    while pages < max_pages:
        params = {"state": "CLOSED", "instrument": "EUR_USD", "count": page_size}
        if before is not None:
            params["beforeID"] = str(before)
        payload = client.request(trades.TradesList(account, params=params))
        rows = payload["trades"]
        if not isinstance(rows, list):
            raise ValueError("Invalid trade page")
        pages += 1
        if not rows:
            break
        ids = [int(row["id"]) for row in rows]
        if min(ids) <= 0 or (before is not None and max(ids) > before):
            raise ValueError("Trade pagination did not advance")
        for row in rows:
            if row.get("instrument") != "EUR_USD" or row.get("state") != "CLOSED":
                raise ValueError("Unexpected instrument or state")
            key = str(row["id"])
            if key in records:
                raise ValueError("Duplicate broker trade in pagination")
            units = Decimal(amount(row["initialUnits"]))
            if units == 0:
                raise ValueError("Invalid initial units")
            ownership = classify_remote_trade(row)
            closing_ids = list(dict.fromkeys(str(x) for x in row.get("closingTransactionIDs", [])))
            closes = []
            # Preserve broker-confirmed reasons for bot trades, not inferred exits.
            if ownership == "bot":
                for txid in closing_ids:
                    tx = client.request(transactions.TransactionDetails(account, transactionID=txid))["transaction"]
                    affected = list(tx.get("tradesClosed") or [])
                    if tx.get("tradeReduced"):
                        affected.append(tx["tradeReduced"])
                    if str(tx.get("id")) != txid or not any(str(t.get("tradeID")) == key for t in affected):
                        raise ValueError("Closing transaction does not reference trade")
                    closes.append({"id": txid, "type": tx.get("type"), "reason": tx.get("reason"), "time": tx.get("time")})
            ext = row.get("clientExtensions") or row.get("tradeClientExtensions") or {}
            records[key] = {
                "trade_id": key, "symbol": "EUR/USD", "ownership": ownership,
                "ownership_stamp": ext.get("id") if ownership == "bot" else None,
                "side": "BUY" if units > 0 else "SELL", "initial_units": str(units),
                "opened_at": row["openTime"], "closed_at": row["closeTime"],
                "entry_price": amount(row["price"]),
                "average_close_price": amount(row["averageClosePrice"]) if row.get("averageClosePrice") is not None else None,
                "price_pl": amount(row["realizedPL"]),
                "financing": amount(row["financing"]) if row.get("financing") is not None else None,
                "closing_transaction_ids": closing_ids, "close_evidence": closes,
                "deployment_version": "unknown_legacy", "initial_risk": None,
                "entry_features": None, "eligible_for_live_learning": False,
            }
        before = min(ids) - 1  # beforeID is the maximum allowed ID, inclusive.
    else:
        raise ValueError("Pagination limit reached; no complete snapshot produced")
    ordered = sorted(records.values(), key=lambda r: int(r["trade_id"]))
    summaries = {}
    for owner in ("bot", "human"):
        subset = [r for r in ordered if r["ownership"] == owner]
        summaries[owner] = {
            "closed_trades": len(subset),
            "price_pl": str(sum((Decimal(r["price_pl"]) for r in subset), Decimal(0))),
            "financing_known": str(sum((Decimal(r["financing"]) for r in subset if r["financing"] is not None), Decimal(0))),
            "financing_missing": sum(r["financing"] is None for r in subset),
        }
    return {"schema_version": 1, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "account_fingerprint": hashlib.sha256(("practice:" + account).encode()).hexdigest(),
            "environment": "practice", "symbol": "EUR/USD", "scope": "broker_returned_closed_trades",
            "pagination_complete": True, "pages": pages, "validated_for_live": False,
            "limitations": ["Unknown historical deployment and initial risk; excluded from live learning.",
                            "Price P/L and financing are separate; no all-cost net-return claim.",
                            "Broker-returned history is not proof of coverage before account retention."],
            "summary": summaries, "trades": ordered}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/research/broker-history"))
    args = parser.parse_args()
    from loguru import logger
    from src.data.fetcher import OandaClient
    logger.disable("src.data.fetcher")  # Exceptions may contain account URLs.
    try:
        report = recover(OandaClient())
    except Exception as exc:
        raise SystemExit(f"History recovery failed ({type(exc).__name__}); no snapshot written.") from None
    args.output_dir.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
    path = args.output_dir / name
    # New immutable snapshot; never replaces a previous successful recovery.
    with path.open("x") as out:
        json.dump(report, out, indent=2)
        out.write("\n")
    print(json.dumps({"path": str(path), "summary": report["summary"], "pagination_complete": True}))


if __name__ == "__main__":
    main()
