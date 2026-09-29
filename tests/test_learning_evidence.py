from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import json

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.analysis.evidence import decision_context
from src.analysis.growth import _score, study_book, growth_gate, GrowthReport, BucketStats
from src.analysis.reflection import record_entry, record_exit
from src.config import Settings
from src.data.storage import Base, Trade, TradeJournal, SignalRow, DecisionObservation, insert_signal
from test_growth import _signal


@pytest.fixture
def session():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def trade(session, **kwargs):
    values = dict(symbol='EUR/USD', side='SELL', units=10000, remaining_units=10000,
                  requested_entry=1.1, fill_price=1.1, stop_loss=1.101,
                  take_profit_1=1.099, take_profit_2=1.098, broker_take_profit=1.098,
                  source='bot', venue='oanda', status='open', opened_at=datetime.now(timezone.utc))
    values.update(kwargs)
    row = Trade(**values)
    session.add(row)
    session.flush()
    return row


def test_scratch_costs_and_unknown_profit_factor():
    rows = [SimpleNamespace(outcome=o, realized_pl=p, entry_context={'initial_risk':
            {'basis':'entry_snapshot', 'currency':'USD', 'amount':risk}})
            for o,p,risk in [('win',100,100), ('loss',-20,10), ('scratch',-2,10)]]
    score = _score(rows,key='x',scope='book')
    assert score.samples == 3 and score.scratches == 1
    assert score.net_pl == 78 and score.expectancy == 26
    assert score.mean_r == pytest.approx(-.4)  # Dollar profits conceal negative R expectancy.
    assert score.profit_factor == pytest.approx(100/22)
    assert _score(rows[:1],key='x',scope='book').profit_factor is None
    assert score.evidence_status == 'insufficient_evidence'


@pytest.mark.parametrize('amount',[None, 0, -1, float('nan'), float('inf'), 'bad'])
def test_invalid_risk_never_fabricates_r(amount):
    row=SimpleNamespace(outcome='win',realized_pl=10,entry_context={'initial_risk':
                        {'basis':'entry_snapshot','currency':'USD','amount':amount}})
    score=_score([row],key='x',scope='book')
    assert score.r_samples == 0 and score.mean_r is None and score.missing_risk_samples == 1


def test_initial_risk_survives_stop_change(session):
    row=trade(session)
    sig=_signal(decision_context={'account':{'currency':'USD'}})
    journal=record_entry(session,row,sig)
    assert journal.entry_context['initial_risk']['amount'] == pytest.approx(10)
    row.stop_loss=1.1
    row.remaining_units=5000
    record_entry(session,row,sig)
    assert journal.entry_context['initial_risk']['amount'] == pytest.approx(10)
    assert journal.entry_context['initial_risk']['units'] == 10000


@pytest.mark.parametrize('overrides,context,adopted',[
    ({'status':'closed'},{'account':{'currency':'USD'}},False),
    ({},{'account':{'currency':'EUR'}},False),
    ({},{},False), ({},{'account':{'currency':'USD'}},True),
])
def test_no_risk_backfill_or_currency_guess(session,overrides,context,adopted):
    row=trade(session,**overrides)
    journal=record_entry(session,row,_signal(decision_context=context),adopted=adopted)
    assert 'initial_risk' not in journal.entry_context


def test_manual_losses_and_wins_separate_copies_excluded(session):
    for source,venue,parent,pl in [('bot','oanda',None,10),('human','oanda',None,100),
                                ('human','oanda',None,-80),('bot','mt4',1,50)]:
        row=trade(session,source=source,venue=venue,parent_trade_id=parent)
        record_entry(session,row,_signal())
        row.status='closed'; row.closed_at=datetime.now(timezone.utc)
        record_exit(session,row,exit_price=1.099,realized_pl=pl,close_reason='broker_closed',settings=Settings())
    report=study_book(session,settings=Settings())
    assert report.bucket('EUR/USD|SELL').samples == 1
    assert report.bucket('EUR/USD|SELL').net_pl == 10
    assert report.bucket('human:EUR/USD|SELL').samples == 2
    assert report.bucket('human:EUR/USD|SELL').net_pl == 20
    assert report.preferred_side is None
    assert growth_gate(_signal(),report,settings=Settings()).action == 'observe'


def test_legacy_teacher_and_stop_recommendations_cannot_raise_risk():
    sig=_signal(action='BUY',strength=10)
    from src.analysis.reflection import fingerprint_from_signal
    report=GrowthReport(ts=datetime.now(timezone.utc),preferred_side='BUY',recommended_min_stop_pips=12,
                        buckets=[BucketStats(key=fingerprint_from_signal(sig),scope='exact',teacher_wins=20)])
    result=growth_gate(sig,report,intel={'h1_bias':'bearish','d1_bias':'bearish'},settings=Settings(min_stop_pips=5))
    assert not result.allowed and result.min_stop_pips == 5


def test_source_snapshot_allowlist_and_repeated_decisions(session):
    settings=Settings()
    now=datetime.now(timezone.utc)
    frame=pd.DataFrame({'open':[1.1],'high':[1.2],'low':[1.0],'close':[1.11]},index=[now])
    context=decision_context(settings=settings,quote=SimpleNamespace(bid=1.1,ask=1.1001,ts=now),
        account=SimpleNamespace(currency='USD',nav=1000,raw={'token':'never-copy-this'}),
        frames={'M5':frame},captured_at=now)
    assert 'never-copy-this' not in json.dumps(context)
    assert len(context['code_sha256']) == 64
    sig=_signal(decision_context=context)
    insert_signal(session,sig.to_row(skipped=True,skip_reason='spread'))
    insert_signal(session,sig.to_row(skipped=True,skip_reason='paused'))
    session.flush()
    assert len(list(session.scalars(select(SignalRow)))) == 1
    observations=list(session.scalars(select(DecisionObservation).order_by(DecisionObservation.id)))
    assert [r.payload['skip_reason'] for r in observations] == ['spread','paused']
    context['account']['nav']=9999
    assert observations[0].payload['decision_context']['account']['nav'] == 1000
    json.dumps(observations[0].payload,allow_nan=False)


def test_report_is_read_only_and_no_database_creation(tmp_path):
    from src.analysis.learning_report import report_database
    from sqlalchemy.exc import OperationalError
    import hashlib
    path=tmp_path/'book.db'
    engine=create_engine(f'sqlite:///{path}')
    Base.metadata.create_all(engine)
    engine.dispose()
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    report=report_database(path)
    assert report['decision_observations']['count'] == 0
    assert report['preferred_side'] is None
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    missing=tmp_path/'missing.db'
    with pytest.raises(OperationalError):
        report_database(missing)
    assert not missing.exists()


def test_closed_time_not_journal_refresh_orders_growth(session):
    now=datetime.now(timezone.utc)
    for i,pl in enumerate([10,-2,-3]):
        row=trade(session,status='closed',closed_at=now+timedelta(minutes=i))
        session.add(TradeJournal(trade_id=row.id,symbol='EUR/USD',side='SELL',
            outcome='win' if pl>0 else 'loss',realized_pl=pl,
            updated_at=now-timedelta(minutes=i)))
    session.flush()
    assert study_book(session,settings=Settings()).bucket('EUR/USD|SELL').losing_streak == 2


def test_stop_losses_do_not_widen_configured_floor(session):
    for _ in range(2):
        row=trade(session,stop_loss=1.1005)
        sig=_signal(decision_context={'account':{'currency':'USD'}})
        record_entry(session,row,sig)
        row.status='closed'; row.closed_at=datetime.now(timezone.utc)
        record_exit(session,row,exit_price=1.1005,realized_pl=-5,close_reason='stop_loss',settings=Settings())
    report=study_book(session,settings=Settings(min_stop_pips=5))
    assert report.stop_out_count == 2
    assert report.recommended_min_stop_pips == 5


def test_unvalidated_history_cannot_steer_written_goals():
    from src.analysis.desk import _goals
    from datetime import date
    history=SimpleNamespace(preferred_side='SELL',validated_for_live=False)
    assert 'History from extra datasets' not in _goals({},[],date(2026,9,25),Settings(),history)


def test_session_labels_follow_dst():
    from src.analysis.growth import hour_bucket
    assert hour_bucket(datetime(2026,1,15,12,tzinfo=timezone.utc)) == 'london'
    assert hour_bucket(datetime(2026,7,15,12,tzinfo=timezone.utc)) == 'overlap'
    # US summer time has started, UK summer time has not.
    assert hour_bucket(datetime(2026,3,16,12,tzinfo=timezone.utc)) == 'overlap'
    assert hour_bucket(datetime(2026,7,15,12)) == 'overlap'
