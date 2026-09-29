"""Offline broker contract regressions: no real API or credentials."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.trades as trades
from oandapyV20.exceptions import V20Error
from requests.exceptions import Timeout

from src.config import Settings
from src.data.fetcher import OandaClient, FeedError, Quote
from src.execution.paper_broker import PaperBroker, BrokerError
from src.execution.instance_lock import InstanceLock
from src.execution.order_intent import claim_entry
from src.execution.trade_guard import should_take_partial
from src.pipeline import TradingPipeline


def broker(responses):
    client = Mock(account_id='test')
    client.request.side_effect = responses
    b = PaperBroker(Settings(_env_file=None), client)
    b._precision['EUR/USD'] = 5
    return b


def owned(**extra):
    return {'id':'7','state':'OPEN','currentUnits':'100','clientExtensions':{'id':'fs-test'},**extra}


def test_transport_failure_does_not_replay_writes_and_survives_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, oanda_account_id='test')
    client = OandaClient(settings)
    client._api = Mock()
    client._api.request.side_effect = Timeout('timeout')
    with pytest.raises(FeedError, match='unknown'):
        client.request(orders.OrderCreate('test',data={'order':{}}))
    assert client._api.request.call_count == 1
    restarted = OandaClient(settings)
    restarted._api = Mock()
    with pytest.raises(FeedError, match='paused'):
        restarted.request(trades.TradeClose('test',tradeID='7',data={'units':'ALL'}))
    restarted._api.request.assert_not_called()
    restarted._api.request.return_value = {'trades':[]}
    assert restarted.request(trades.OpenTrades('test')) == {'trades':[]}


def test_definitive_rejection_not_retried(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = OandaClient(Settings(_env_file=None))
    client._api = Mock()
    client._api.request.side_effect = V20Error(400, 'invalid order')
    with pytest.raises(V20Error):
        client.request(orders.OrderCreate('test',data={}))
    assert client._api.request.call_count == 1
    assert not client._write_latch().exists()


def test_get_can_reconnect_once(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    client=OandaClient(Settings(_env_file=None))
    client._api=Mock()
    client._api.request.side_effect=[Timeout(),{'trades':[]}]
    client.reconnect=Mock()
    assert client.request(trades.OpenTrades('test'))=={'trades':[]}
    assert client._api.request.call_count==2


def test_live_mutations_are_blocked(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    client=OandaClient(Settings(_env_file=None,oanda_environment='live'))
    client._api=Mock()
    with pytest.raises(FeedError,match='practice'):
        client.request(orders.OrderCreate('test',data={}))
    client._api.request.assert_not_called()


@pytest.mark.parametrize('method', ['close','modify','annotate'])
def test_broker_boundary_refuses_manual_trade(method):
    b=broker([{'trade':owned(clientExtensions={'id':'manual','tag':'EURUSD'})}])
    with pytest.raises(BrokerError,match='Operator'):
        if method=='close': b.close_trade('7')
        elif method=='modify': b.modify_trade('7',symbol='EUR/USD',stop_loss=1.1)
        else: b.annotate_trade('7',comment='test')
    assert b.client.request.call_count==1  # Read only, no mutation.


def test_cancelled_close_is_not_a_sale():
    b=broker([{'trade':owned()},{'orderCancelTransaction':{'reason':'MARKET_HALTED'}}])
    with pytest.raises(BrokerError,match='MARKET_HALTED'): b.close_trade('7')


@pytest.mark.parametrize('reduction', ['tradeReduced','tradesClosed'])
def test_confirmed_partial_and_full_close(reduction):
    item={'tradeID':'7','units':'50','realizedPL':'4.20'}
    fill={'price':'1.101','pl':'4.20',reduction:item if reduction=='tradeReduced' else [item]}
    b=broker([{'trade':owned()},{'orderFillTransaction':fill}])
    payload=b.close_trade('7',units='50')
    assert b.realized_pl_from_close(payload)==(1.101,4.2)


def test_unconfirmed_close_pauses_writes():
    b=broker([{'trade':owned()},{'orderCreateTransaction':{'id':'8'}}])
    with pytest.raises(BrokerError): b.close_trade('7')
    b.client.pause_writes.assert_called_once()


def test_open_has_unique_stamp_protection_and_slippage_bound():
    response={'orderCreateTransaction':{'id':'6'},'orderFillTransaction':{'id':'7','price':'1.1001','tradeOpened':{'tradeID':'7','units':'100'}}}
    b=broker([response,response])
    for _ in range(2):
        result=b.place_market_order(symbol='EUR/USD',side='BUY',units=100,requested_entry=1.1,stop_loss=1.099,take_profit=1.102)
        assert result.ok and result.stop_loss==pytest.approx(1.099)
    bodies=[call.args[0].data['order'] for call in b.client.request.call_args_list]
    assert bodies[0]['clientExtensions']['id']!=bodies[1]['clientExtensions']['id']
    assert bodies[0]['stopLossOnFill']['price']=='1.09900'
    assert bodies[0]['takeProfitOnFill']['price']=='1.10200'
    assert bodies[0]['priceBound']=='1.10015'
    assert bodies[0]['positionFill']=='OPEN_ONLY'
    assert b.client.request.call_count==2  # No naked-fill then attach sequence.


def test_empty_open_response_not_successful():
    b=broker([{}])
    with pytest.raises(BrokerError,match='confirmed'):
        b.place_market_order(symbol='EUR/USD',side='BUY',units=100,requested_entry=1.1,stop_loss=1.099,take_profit=1.102)
    b.client.pause_writes.assert_called_once()


def test_missing_close_pl_is_not_estimated():
    with pytest.raises(BrokerError): broker([]).realized_pl_from_close({'orderFillTransaction':{'price':'1.1'}})


def test_instance_lock_excludes_second_instance_and_releases(tmp_path):
    with InstanceLock('test',tmp_path):
        with pytest.raises(RuntimeError):
            with InstanceLock('test',tmp_path): pass
    with InstanceLock('test',tmp_path): pass


def test_entry_reservation_survives_repeated_calls(tmp_path):
    assert claim_entry('a','EUR/USD','2026-01-01T12:00Z',tmp_path)
    assert not claim_entry('a','EUR/USD','2026-01-01T12:00Z',tmp_path)
    assert claim_entry('a','EUR/USD','2026-01-01T12:05Z',tmp_path)


@pytest.mark.parametrize('bad', [None,float('nan'),-1,0])
def test_partial_requires_proven_positive_pl(bad):
    t=SimpleNamespace(source='bot',side='BUY',fill_price=1.1,take_profit_1=1.101,remaining_units=100,tp1_filled=False)
    assert not should_take_partial(t,mark=1.102,unrealized_pl=bad)[0]


def test_wrong_side_target_cannot_close_in_profit():
    t=SimpleNamespace(source='bot',side='BUY',fill_price=1.1,take_profit_1=1.099,remaining_units=100,tp1_filled=False)
    assert not should_take_partial(t,mark=1.102,unrealized_pl=10)[0]


@pytest.mark.parametrize('source,age,tradeable', [('oanda',91,True),('currencyfreaks',0,True),('oanda',0,False)])
def test_management_rejects_stale_fallback_or_closed_quotes(source,age,tradeable):
    p=TradingPipeline.__new__(TradingPipeline)
    p.settings=Settings(_env_file=None)
    q=Quote('EUR/USD',1.1,1.1002,1.1001,.0002,tradeable,datetime.now(timezone.utc)-timedelta(seconds=age),source)
    assert not p._management_quote_ready(q)


def test_missing_trade_requires_broker_closed_state():
    p=TradingPipeline.__new__(TradingPipeline)
    p.broker=Mock()
    p.broker.trade_details.return_value=owned()
    t=SimpleNamespace(venue='oanda',broker_trade_id='7',status='open',remaining_units=100)
    with pytest.raises(RuntimeError,match='Unresolved'):
        p._mark_closed_missing(Mock(),t,Mock())
    assert t.status=='open' and t.remaining_units==100


def test_closed_reconciliation_uses_total_pl_not_booked_partial_or_mid(monkeypatch):
    p=TradingPipeline.__new__(TradingPipeline)
    p.broker=Mock()
    p.broker.trade_details.return_value=owned(state='CLOSED',averageClosePrice='1.099',realizedPL='-25',closeTime='2026-09-21T12:00:00Z')
    p._quotes={'EUR/USD':SimpleNamespace(mid=1.2)}
    p.slack=Mock()
    p._ingest_journal_into_playbook=Mock()
    p._mirror_mt4_close=Mock()
    p.settings=Settings(_env_file=None)
    t=SimpleNamespace(id=1,symbol='EUR/USD',venue='oanda',broker_trade_id='7',status='partial',remaining_units=50,realized_pl=10,exit_price=None)
    monkeypatch.setattr('src.pipeline.get_or_create_daily_pnl',lambda *a:SimpleNamespace(trades_closed=0))
    journal=Mock()
    monkeypatch.setattr('src.pipeline.record_exit',journal)
    p._mark_closed_missing(Mock(),t,SimpleNamespace(balance=1000))
    assert t.realized_pl==-25 and t.exit_price==1.099
    assert t.closed_at==datetime(2026,9,21,12,tzinfo=timezone.utc)
    assert t.close_reason=='broker_closed' and t.status=='closed'
    assert journal.call_args.kwargs['realized_pl']==-25


def test_cancelled_partial_keeps_local_state():
    p=TradingPipeline.__new__(TradingPipeline)
    p.settings=Settings(_env_file=None)
    p._quotes={'EUR/USD':Quote('EUR/USD',1.1012,1.1014,1.1013,.0002,True,datetime.now(timezone.utc),'oanda')}
    b=broker([{'trade':owned()},{'orderCancelTransaction':{'reason':'MARKET_HALTED'}}])
    p._exec_broker=lambda t:b
    t=SimpleNamespace(source='bot',symbol='EUR/USD',side='BUY',fill_price=1.1,take_profit_1=1.101,
                      remaining_units=100,units=100,tp1_filled=False,status='open',broker_trade_id='7',realized_pl=0)
    p._maybe_take_partial(Mock(),t,{'unrealizedPL':'10'})
    assert t.status=='open' and not t.tp1_filled and t.remaining_units==100


def test_partial_trigger_uses_bid_not_mid_for_buy():
    p=TradingPipeline.__new__(TradingPipeline)
    p.settings=Settings(_env_file=None)
    p._quotes={'EUR/USD':Quote('EUR/USD',1.1009,1.1013,1.1011,.0004,True,datetime.now(timezone.utc),'oanda')}
    p._exec_broker=Mock()
    t=SimpleNamespace(source='bot',symbol='EUR/USD',side='BUY',fill_price=1.1,take_profit_1=1.101,
                      remaining_units=100,units=100,tp1_filled=False,status='open')
    p._maybe_take_partial(Mock(),t,{'unrealizedPL':'10'})
    p._exec_broker.assert_not_called()


def test_cancelled_close_cools_down_instead_of_spamming_broker():
    b=broker([{'trade':owned()},{'orderCancelTransaction':{'reason':'FIFO_VIOLATION'}}])
    with pytest.raises(BrokerError): b.close_trade('7')
    with pytest.raises(BrokerError,match='cooling'): b.close_trade('7')
    assert b.client.request.call_count==2


def test_friday_flat_even_for_new_bot_trade(monkeypatch):
    now=datetime(2026,9,18,20,0,tzinfo=timezone.utc)
    monkeypatch.setattr('src.pipeline.utcnow',lambda:now)
    p=TradingPipeline.__new__(TradingPipeline)
    p.settings=Settings(_env_file=None)
    p._quotes={'EUR/USD':Quote('EUR/USD',1.1,1.1002,1.1001,.0002,True,now,'oanda')}
    b=Mock()
    b.close_trade.side_effect=BrokerError('test cancellation')
    p._exec_broker=lambda t:b
    t=SimpleNamespace(source='bot',symbol='EUR/USD',opened_at=now-timedelta(minutes=2),broker_trade_id='7')
    p._maybe_time_stop(Mock(),t,{},Mock())
    b.close_trade.assert_called_once_with('7',units='ALL')


def test_exploratory_history_cannot_veto_live_direction():
    from src.analysis.growth import growth_gate
    from src.data.datasets import HistoryReport
    from tests.test_datasets import _signal
    history=HistoryReport(ts=datetime.now(timezone.utc),found=True,replay_trades=500,preferred_side='SELL')
    result=growth_gate(_signal(action='BUY',strength=50),None,history=history,settings=Settings(_env_file=None))
    assert result.allowed

@pytest.mark.parametrize('side,fill,stop,target', [('BUY','1.1001',1.099,1.102),('SELL','1.0999',1.101,1.098)])
def test_slippage_never_moves_original_stop(side,fill,stop,target):
    b=broker([{'orderFillTransaction':{'id':'7','price':fill,'tradeOpened':{'tradeID':'7','units':'100' if side=='BUY' else '-100'}}}])
    result=b.place_market_order(symbol='EUR/USD',side=side,units=100,requested_entry=1.1,stop_loss=stop,take_profit=target)
    order=b.client.request.call_args.args[0].data['order']
    assert 'distance' not in order['stopLossOnFill']
    assert float(order['stopLossOnFill']['price'])==stop
    assert result.stop_loss==stop


def test_final_check_rejects_spread_expansion_and_paused_entries(monkeypatch):
    from test_growth import _signal
    p=TradingPipeline.__new__(TradingPipeline)
    p.settings=Settings(_env_file=None)
    p.trading_enabled=True
    p._quotes={}
    p.fetcher=Mock()
    signal=_signal(entry=1.1,price=1.1,stop_loss=1.101,take_profit_1=1.099,take_profit_2=1.098)
    q=Quote('EUR/USD',1.1,1.1003,1.10015,.0003,True,datetime.now(timezone.utc),'oanda')
    p.fetcher.fetch_quotes.return_value=[q]
    monkeypatch.setattr('src.pipeline.calendar_hold_reason',lambda *a,**k: None)
    assert 'spread' in p._final_entry_check(signal)
    q=Quote('EUR/USD',1.1,1.1001,1.10005,.0001,True,datetime.now(timezone.utc),'oanda')
    p.fetcher.fetch_quotes.return_value=[q]
    assert p._final_entry_check(signal) is None
    p.trading_enabled=False
    assert 'paused' in p._final_entry_check(signal)
    p.fetcher.fetch_quotes.side_effect=RuntimeError('network')
    assert 'refresh failed' in p._final_entry_check(signal)

@pytest.mark.parametrize('quantity', ['NaN','Infinity',None,'bad','0','49'])
def test_invalid_close_quantity_requires_durable_reconciliation(quantity):
    fill={'price':'1.101','pl':'1','tradeReduced':{'tradeID':'7','units':quantity}}
    b=broker([{'trade':owned()},{'orderFillTransaction':fill}])
    with pytest.raises(BrokerError,match='not confirmed'):
        b.close_trade('7',units='50')
    b.client.pause_writes.assert_called_once()


def test_missing_per_trade_pl_is_not_a_zero_close():
    fill={'price':'1.101','tradesClosed':[{'tradeID':'7','units':'100'}]}
    b=broker([{'trade':owned()},{'orderFillTransaction':fill}])
    with pytest.raises(BrokerError,match='incomplete'):
        b.close_trade('7')
    b.client.pause_writes.assert_called_once()


def test_partial_close_per_trade_pl_fallback_preserves_zero():
    fill={'price':'1.101','tradeReduced':{'tradeID':'7','units':'50','realizedPL':'0'}}
    b=broker([{'trade':owned()},{'orderFillTransaction':fill}])
    payload=b.close_trade('7',units='50')
    assert b.realized_pl_from_close(payload)==(1.101,0.0)
    b.client.pause_writes.assert_not_called()


def test_unrelated_reduction_cannot_contaminate_close_pl():
    fill={'price':'1.101','pl':'15','tradesClosed':[{'tradeID':'7','units':'100'},{'tradeID':'8','units':'10'}]}
    b=broker([{'trade':owned()},{'orderFillTransaction':fill}])
    with pytest.raises(BrokerError): b.close_trade('7')
    b.client.pause_writes.assert_called_once()

@pytest.mark.parametrize('changed', [{'price':'NaN'}, {'units':'NaN'}, {'units':'99'}, {'units':'-100'}])
def test_invalid_opened_trade_latches_uncertainty(changed):
    opened={'tradeID':'7','units':'100','price':'1.1001',**changed}
    b=broker([{'orderFillTransaction':{'price':'1.1001','tradeOpened':opened}}])
    with pytest.raises(BrokerError,match='Opening fill invalid'):
        b.place_market_order(symbol='EUR/USD',side='BUY',units=100,requested_entry=1.1,stop_loss=1.099,take_profit=1.102)
    b.client.pause_writes.assert_called_once()


def test_open_uses_trade_specific_execution_price():
    b=broker([{'orderFillTransaction':{'price':'1.1000','tradeOpened':{'tradeID':'7','units':'100','price':'1.1001'}}}])
    result=b.place_market_order(symbol='EUR/USD',side='BUY',units=100,requested_entry=1.1,stop_loss=1.099,take_profit=1.102)
    assert result.fill_price==1.1001
    assert result.slippage_pips==pytest.approx(1)
