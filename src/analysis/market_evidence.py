"""Read-only OANDA practice bid/ask candle export for diagnostic replay."""
import argparse,json
from pathlib import Path
from datetime import datetime,timezone,timedelta
from src.analysis.trade_excursions import fetch_window
from src.analysis.execution_assumptions import ExecutionAssumptions


def candle_map(rows):
    return {r['time']: {'bid':r['bid'],'ask':r['ask']} for r in rows if r.get('complete')}


def main():
    from src.data.fetcher import OandaClient
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--days',type=int,default=3)
    args=parser.parse_args()
    if not 1<=args.days<=7:parser.error('Use 1..7 days')
    if args.output.exists():parser.error('Output already exists')
    client=OandaClient()
    if client.settings.oanda_environment!='practice':parser.error('Practice only')
    now=datetime.now(timezone.utc)
    bars=candle_map(fetch_window(client,now-timedelta(days=args.days),now-timedelta(minutes=2)))
    values={'market_bars':bars,'provenance':'OANDA practice EUR_USD complete M1 bid/ask; fees unknown'}
    ExecutionAssumptions(**values)
    with args.output.open('x') as out:json.dump(values,out)
    print('Measured candles:',len(bars))

if __name__=='__main__':main()
