"""Durable at-most-once entry attempts per account/symbol/candle.

A rejected or interrupted attempt consumes the candle. This deliberately favors
missing a trade over duplicating one after a crash or scheduler retry.
"""
import hashlib
import json
import os
from pathlib import Path


def claim_entry(account: str, symbol: str, candle: str, directory: Path = Path('data/order-intents')) -> bool:
    key = hashlib.sha256(f'{account}|{symbol}|{candle}'.encode()).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with (directory / f'{key}.json').open('x') as handle:
            json.dump({'symbol': symbol, 'candle': candle, 'status': 'attempt_reserved'}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        return True
    except FileExistsError:
        return False
