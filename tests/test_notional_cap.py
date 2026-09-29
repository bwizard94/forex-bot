import pytest
from src.config import Settings
from src.execution.risk_manager import AccountState, RiskManager, notional_unit_cap

@pytest.mark.parametrize('side,stop', [('BUY',1.099),('SELL',1.101)])
def test_ten_percent_is_order_value_not_stop_risk(side,stop):
    settings=Settings(_env_file=None,max_order_notional_pct=.1)
    account=AccountState(100000,200000,0,0,0,200000,0)
    units,risk,_=RiskManager(settings).size_position(symbol='EUR/USD',side=side,entry=1.1,
        stop_loss=stop,account=account)
    assert units==9090
    assert units*1.1<=10000
    assert risk==pytest.approx(9.09)


def test_lower_risk_limit_wins_over_order_value():
    s=Settings(_env_file=None,max_order_notional_pct=.1,risk_per_trade_pct=.000001)
    a=AccountState(100000,100000,0,0,0,100000,0)
    units,_,_=RiskManager(s).size_position(symbol='EUR/USD',side='BUY',entry=1.1,stop_loss=1.099,account=a)
    assert units<=100


def test_sell_notional_uses_higher_price_not_adverse_lower_price():
    s=Settings(_env_file=None,max_order_notional_pct=.1)
    a=AccountState(100000,100000,0,0,0,100000,0)
    units,_,_=RiskManager(s).size_position(symbol='EUR/USD',side='SELL',entry=1.1,
        stop_loss=1.101,notional_price=1.2,account=a)
    assert units==8333


@pytest.mark.parametrize('balance,currency', [(float('nan'),'USD'),(-1,'USD'),(100000,'EUR')])
def test_invalid_balance_or_unsupported_currency_blocks(balance,currency):
    s=Settings(_env_file=None,max_order_notional_pct=.1)
    a=AccountState(balance,100000,0,0,0,100000,0,currency=currency)
    assert notional_unit_cap(s,a,1.1)==0
