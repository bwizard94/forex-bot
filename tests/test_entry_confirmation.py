import pandas as pd
import pytest
from src.analysis.entry_confirmation import directional_strength, evidence_families, price_confirmation, reentry_reason


def bars():
    return pd.DataFrame({'open':[1.10,1.10], 'high':[1.1002,1.1005],
                         'low':[1.0998,1.0999], 'close':[1.10,1.1004]},
                        index=pd.date_range('2026-09-30T12:00Z', periods=2, freq='min'))


def test_opposing_votes_cannot_inflate_selected_side():
    bull=['RSI oversold (25)', 'H1 trend bullish']
    bear=['EMA 9 below EMA 21', 'MACD histogram negative', 'H1 trend bearish',
          'Close at/over upper Bollinger band', 'Liquidity sweep of prior highs']
    assert directional_strength('BUY',bull,bear)==20
    assert directional_strength('SELL',bull,bear)==50
    assert directional_strength('HOLD',bull,bear)==0


def test_correlated_oscillators_are_one_family_and_capped():
    factors=['RSI oversold','Stochastic oversold','CCI oversold','WaveTrend oversold',
             'MACD bullish cross','DSS of momentum green']
    assert evidence_families(factors)==['momentum']
    assert directional_strength('BUY',factors,[])==25


def test_price_requires_close_beyond_previous_extreme_and_direction():
    f=bars()
    assert price_confirmation('BUY',f,'M1')
    assert not price_confirmation('SELL',f,'M1')
    f.iloc[-1,f.columns.get_loc('close')]=1.1001
    assert not price_confirmation('BUY',f,'M1')  # wick alone cannot confirm
    f.iloc[-1,f.columns.get_loc('close')]=1.1004
    f.iloc[-1,f.columns.get_loc('open')]=1.1005
    assert not price_confirmation('BUY',f,'M1')  # wrong-way body


def test_sell_confirmation_is_symmetric():
    f=bars()
    for k in ('open','high','low','close'): f[k]=2.2-f[k]
    f['high'],f['low']=f['low'].copy(),f['high'].copy()
    assert price_confirmation('SELL',f,'M1')


def test_missing_or_nonfinite_confirmation_fails_closed():
    f=bars();f.index=[f.index[0],f.index[-1]+pd.Timedelta(minutes=1)]
    assert not price_confirmation('BUY',f,'M1')
    f=bars();f.iloc[-1,f.columns.get_loc('close')]=float('nan')
    assert not price_confirmation('BUY',f,'M1')
    assert not price_confirmation('BUY',bars().iloc[:1],'M1')


def test_reentry_requires_post_loss_bar_but_not_a_broad_ban():
    f=bars();prior={'side':'BUY','pl':-50,'closed_at':f.index[-1]+pd.Timedelta(seconds=1)}
    assert reentry_reason('BUY',f,'M1',prior)
    prior['closed_at']=f.index[-1]
    assert reentry_reason('BUY',f,'M1',prior) is None
    prior['closed_at']=f.index[-1]+pd.Timedelta(hours=1)
    assert reentry_reason('SELL',f,'M1',prior) is None
    prior['pl']=1
    assert reentry_reason('BUY',f,'M1',prior) is None


def test_latest_loss_context_excludes_human_mirror_and_rejected_orders():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from src.data.storage import Base, Trade
    from src.analysis.entry_confirmation import latest_bot_close
    engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
    with Session(engine) as session:
        for i,extra in enumerate([{}, {'source':'human'}, {'venue':'mt4'}, {'parent_trade_id':1}, {'status':'rejected'}]):
            row=Trade(symbol='EUR/USD',side='BUY',units=100,requested_entry=1.1,stop_loss=1.099,
                      take_profit_1=1.101,take_profit_2=1.102,broker_take_profit=1.102,
                      source='bot',venue='oanda',status='closed',realized_pl=-10,
                      closed_at=(pd.Timestamp('2026-09-30T12:00Z')+pd.Timedelta(minutes=i)).to_pydatetime())
            for k,v in extra.items():setattr(row,k,v)
            session.add(row)
        session.flush()
        assert latest_bot_close(session,'EUR/USD').id==1
        assert latest_bot_close(session,'GBP/USD') is None


def test_countertrend_signal_needs_price_reversal_not_only_oversold_votes(monkeypatch):
    from src.analysis import signals
    from src.config import Settings
    f=bars()
    for key,value in {'ema_fast':1.0999,'ema_slow':1.1002,'rsi':30,'atr':.0003,
                      'bb_upper':1.12,'bb_mid':1.11,'bb_lower':1.09,'stoch_k':20,'cci':-120}.items():f[key]=value
    htf=f.copy();htf['ema_fast']=1.102;htf['ema_slow']=1.10
    monkeypatch.setattr(signals,'compute_indicators',lambda b,**kw:b)
    monkeypatch.setattr(signals,'detect_rsi_divergence',lambda *a:None)
    settings=Settings(_env_file=None,session_filter=False,min_rr_ratio=1,confirmed_entry_policy=True)
    confirmed=signals.evaluate_signal('EUR/USD','M1',f,htf_bars=htf,settings=settings)
    assert confirmed.action=='BUY'
    f.iloc[-1,f.columns.get_loc('close')]=1.1001
    blocked=signals.evaluate_signal('EUR/USD','M1',f,htf_bars=htf,settings=settings)
    assert blocked.action=='HOLD' and 'directional close' in blocked.reason
    assert blocked.entry is None and blocked.stop_loss is None
    assert blocked.strength==0
    f.iloc[-1,f.columns.get_loc('open')]=1.1005
    unguarded=signals.evaluate_signal('EUR/USD','M1',f,htf_bars=htf,
                                     settings=settings.model_copy(update={'confirmed_entry_policy':False}))
    assert unguarded.action=='BUY'
    assert not any('Committed close' in x for x in unguarded.confluence)
    assert unguarded.confirmation_review['allowed'] is False
    assert unguarded.confirmation_review['enabled'] is False


@pytest.mark.parametrize('pl', [-50,50])
def test_contextual_journal_does_not_invent_a_cause_or_promote_a_win(pl):
    from types import SimpleNamespace
    from src.analysis.reflection import build_postmortem
    from src.config import Settings
    ts=pd.Timestamp('2026-09-30T12:00Z').to_pydatetime()
    trade=SimpleNamespace(side='BUY',symbol='EUR/USD',fill_price=1.1,requested_entry=1.1,
                          source='bot',opened_at=ts,closed_at=ts)
    journal=SimpleNamespace(fingerprint='EUR/USD|BUY|bullish|rsi_mid|bb_mid',
                            entry_context={'ema_fast':1.099,'ema_slow':1.1})
    out=build_postmortem(trade=trade,journal=journal,exit_price=1.0995 if pl<0 else 1.1005,
                        realized_pl=pl,close_reason='stop_loss' if pl<0 else 'take_profit',
                        settings=Settings(_env_file=None,practice_contextual_loss_review=True))
    text=' '.join(str(v) for v in out.values())
    assert 'does not establish a cause' in text
    assert 'EMA direction opposed' in text
    assert 'That is chop' not in text and 'skipped for' not in text
    assert out['outcome']==('loss' if pl<0 else 'win')
