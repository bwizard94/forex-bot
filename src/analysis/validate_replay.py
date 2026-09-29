"""Offline chronological replay report; never places orders or changes strategy settings."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pandas as pd

from src.analysis.replay import replay, performance, ReplayCosts
from src.config import Settings


def load_csv(path: Path):
    frame = pd.read_csv(path)
    if 'timestamp' not in frame:
        raise ValueError(f'{path.name}: expected timestamp,open,high,low,close[,volume]')
    frame.index = pd.to_datetime(frame.pop('timestamp'), utc=True, errors='raise')
    frame = frame.sort_index()
    if frame.index.has_duplicates:
        raise ValueError(f'{path.name}: duplicate timestamps')
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('m5','h1','d1'):
        parser.add_argument('--'+name,required=True,type=Path,help='CSV with UTC bar-open timestamp column')
    parser.add_argument('--output',type=Path,default=Path('data/replay-validation.json'))
    parser.add_argument('--train-fraction',type=float,default=.7)
    args=parser.parse_args()
    if not .5 <= args.train_fraction <= .9:
        parser.error('train-fraction must be between 0.5 and 0.9')
    frames=[load_csv(getattr(args,k)) for k in ('m5','h1','d1')]
    m5,h1,d1=frames
    split=int(len(m5)*args.train_fraction)
    if split < 180 or len(m5)-split < 90:
        parser.error('Need at least 180 training bars and 90 holdout bars; more data is needed for useful evidence')
    settings=Settings()  # Same local strategy configuration; no clients are constructed.
    report={
        'model':'exploratory_ohlc_v3','validated_for_live':False,
        'split_at':str(m5.index[split]),'train_fraction':args.train_fraction,
        'source_sha256':{name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                         for name in ('replay.py','signals.py','indicators.py')},
        'files':{k:{'path':str(getattr(args,k).resolve()),'sha256':hashlib.sha256(getattr(args,k).read_bytes()).hexdigest()} for k in ('m5','h1','d1')},
        'assumptions':['UTC bar-open midpoint OHLC','constant spread and adverse per-fill slippage',
                       'stop first when intrabar order is ambiguous','next-bar entries','50% TP1 then breakeven from following bar',
                       'no news-event filter, financing, commissions, risk sizing or portfolio simulation',
                       'fixed original stop price; entry cost/drift/reward-risk gates',
                       'single position; end-of-data exits explicitly counted','holdout must remain untouched during tuning'],
        'configuration':{k:v for k,v in settings.model_dump().items() if k in {
            'trading_style','min_stop_pips','scalp_max_hold_minutes','max_fill_slippage_pips',
            'friday_flat_hour','monday_open_skip_minutes','require_htf_trend','ema_fast','ema_slow','rsi_period','atr_period',
            'atr_sl_multiplier','atr_tp1_multiplier','atr_tp2_multiplier','session_filter','trade_session_start_hour','trade_session_end_hour'}},
        'runs':[],
    }
    for spread in (.8,1.2,1.8):
        costs=ReplayCosts(spread,.2)
        for label,frame,lookback in (
            ('training',m5.iloc[:split],split),
            ('holdout',m5.iloc[max(0,split-180):],len(m5)-split),
        ):
            rows,_=replay(frame,h1,d1,settings,costs=costs,lookback=lookback,max_trades=len(frame))
            report['runs'].append({'period':label,'spread_pips':spread,'slippage_pips':.2,
                                   'metrics':performance(rows),'trades':rows})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,default=str)+'\n')
    print(f'Wrote exploratory report: {args.output}. Live validation remains false.')


if __name__=='__main__':
    main()
