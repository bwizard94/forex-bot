"""Incremental completed bid/ask archive. GET-only; isolated from execution DB."""
import json,sqlite3
from datetime import datetime,timezone,timedelta
from pathlib import Path
from src.analysis.trade_excursions import fetch_window,timestamp
from src.analysis.execution_assumptions import ExecutionAssumptions
from src.analysis.documentation import atomic_write

ROOT=Path(__file__).resolve().parents[2]
ARCHIVE=ROOT/'data/research/measured.sqlite'


def connect(path=ARCHIVE):
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=10)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS candles (ts TEXT PRIMARY KEY, payload TEXT NOT NULL, first_seen TEXT NOT NULL)')
    return db


def store(rows,now,path=ARCHIVE):
    accepted={timestamp(r['time']).isoformat():{'bid':r['bid'],'ask':r['ask']} for r in rows
              if r.get('complete') and timestamp(r['time'])+timedelta(minutes=1)<=now}
    ExecutionAssumptions(market_bars=accepted)
    with connect(path) as db:
        db.executemany('INSERT OR IGNORE INTO candles VALUES (?,?,?)',[(ts,json.dumps(r),now.isoformat()) for ts,r in accepted.items()])
    return len(accepted)


def load(path=ARCHIVE):
    if not path.exists():return {}
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        return {ts:json.loads(payload) for ts,payload in db.execute('SELECT ts,payload FROM candles ORDER BY ts')}


def refresh(path=ARCHIVE,client=None,now=None):
    from src.data.fetcher import OandaClient
    client=client or OandaClient();now=now or datetime.now(timezone.utc)
    if client.settings.oanda_environment!='practice':raise ValueError('Practice only')
    with connect(path) as db:last=db.execute('SELECT MAX(ts) FROM candles').fetchone()[0]
    start=max(now-timedelta(days=7),timestamp(last)-timedelta(minutes=5)) if last else now-timedelta(days=3)
    count=store(fetch_window(client,start,now-timedelta(minutes=2)),now,path)
    status={'state':'complete','finished_at':now.isoformat(),'received_completed_bars':count,
            'latest_bar':max(load(path),default=None),'fees_verified':False,
            'note':'First-seen completed prices retained. Outages beyond seven days remain explicit gaps.'}
    atomic_write(ROOT/'data/research/diagnostics/market-status.json',json.dumps(status))
    return status

if __name__=='__main__':refresh()
