"""Read-only current instrument commission/financing metadata; not historical rates."""
import json
from datetime import datetime,timezone
from pathlib import Path
import oandapyV20.endpoints.accounts as accounts
from src.analysis.documentation import atomic_write


def collect(client):
    if client.settings.oanda_environment!='practice':raise ValueError('Practice only')
    summary=client.request(accounts.AccountSummary(client.account_id))['account']
    instrument=client.request(accounts.AccountInstruments(client.account_id,params={'instruments':'EUR_USD'}))['instruments'][0]
    if instrument['name']!='EUR_USD':raise ValueError('Unexpected instrument')
    return {'captured_at':datetime.now(timezone.utc).isoformat(),'currency':summary['currency'],
            'nav':summary['NAV'],'commission':instrument.get('commission'),
            'financing':instrument.get('financing'),'historical_rates_verified':False,
            'limitations':['Current profile is not historical rate evidence. Financing charge clock requires account-specific evidence.']}


def main():
    from src.data.fetcher import OandaClient
    from src.analysis.research_jobs import REPORTS
    from loguru import logger
    logger.disable('src.data.fetcher')
    profile=collect(OandaClient())
    path=REPORTS/('broker-cost-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
    atomic_write(path,json.dumps(profile,indent=2))
    atomic_write(REPORTS/'broker-cost-current.json',json.dumps(profile,indent=2))
    print('Broker cost profile recorded; currency:',profile['currency'],'commission_present:',profile['commission'] is not None)

if __name__=='__main__':main()
