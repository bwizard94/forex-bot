from types import SimpleNamespace as N
import pytest
from src.analysis.entry_quality import entry_quality
from src.config import Settings


def signal(side='BUY'):
    d=1 if side=='BUY' else -1
    return N(symbol='EUR/USD', action=side, entry=1.1, price=1.1,
             stop_loss=1.1-d*.0006, take_profit_1=1.1+d*.00072,
             take_profit_2=1.1+d*.0012)


@pytest.mark.parametrize('side', ['BUY','SELL'])
def test_executable_side_and_worst_bound(side):
    d=1 if side=='BUY' else -1
    s=signal(side); q=N(ask=1.1, bid=1.1)
    r=entry_quality(s,q,Settings())
    assert r['allowed']
    assert r['worst_entry']==pytest.approx(1.1+d*.00015)
    assert r['reward_risk_at_quote']==pytest.approx(2)
    assert s.entry==1.1  # Levels never shifted to chase a price.


@pytest.mark.parametrize('px', [1.1003,1.0997])
def test_reject_large_moves_in_either_direction(px):
    assert not entry_quality(signal(),N(ask=px,bid=px-.0001),Settings())['allowed']


def test_current_reward_risk_must_still_qualify():
    s=signal();s.take_profit_2=1.10072
    result=entry_quality(s,N(ask=1.1001,bid=1.1),Settings())
    assert not result['allowed'] and 'reward/risk' in result['reason']


def test_nonfinite_and_crossed_target_rejected():
    s=signal()
    assert not entry_quality(s,N(ask=float('nan'),bid=1.1),Settings())['allowed']
    s.take_profit_1=1.10005
    assert not entry_quality(s,N(ask=1.1001,bid=1.1),Settings())['allowed']
