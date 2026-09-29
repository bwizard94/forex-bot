from datetime import datetime, timezone, timedelta
import pytest
from src.analysis.sampling import sampling_policy
from src.config import Settings
from src.execution.risk_manager import pick_risk_fraction


def settings(**kw):
    return Settings(_env_file=None,practice_sampling_enabled=True,
                    practice_sampling_until=datetime.now(timezone.utc)+timedelta(days=7),**kw)


def test_only_active_practice_trial_expands_cost_gate():
    s=settings();now=datetime.now(timezone.utc)
    assert sampling_policy(s,now)['cost_stop_fraction']==.35
    assert sampling_policy(s,now+timedelta(days=8))['cost_stop_fraction']==.25
    assert sampling_policy(s,now+timedelta(days=8))['risk_cap']==.001
    s.oanda_environment='live'
    assert sampling_policy(s,now)['cost_stop_fraction']==.25
    assert not sampling_policy(s,now)['enabled']


@pytest.mark.parametrize('mode,adding,loss', [('observe',False,False),('fade',False,False),('observe',True,False),('observe',False,True)])
def test_all_sizing_modes_capped(mode,adding,loss):
    amount,label=pick_risk_fraction(settings(),strength=99,htf_aligned=True,
              growth_action=mode,adding_to_winner=adding,losing_day=loss)
    assert amount<=.001 and label.startswith('practice-sampling/')


def test_missing_naive_or_expired_deadline_never_relaxes_gate():
    s=settings()
    for until in [None,datetime(2030,1,1),datetime(2020,1,1,tzinfo=timezone.utc)]:
        s.practice_sampling_until=until
        assert not sampling_policy(s)['active']
        assert sampling_policy(s)['risk_cap']==.001


def test_authorized_one_percent_profile_respects_cap_and_expiry():
    s=settings(practice_sampling_risk_cap=.01,risk_per_trade_pct=.01,
               conviction_risk_pct=.01,signal_timeframe='M1',
               daily_loss_limit_pct=.05,daily_soft_halt_pct=.05)
    amount,_=pick_risk_fraction(s,strength=99,htf_aligned=True,
        growth_action='observe',adding_to_winner=False,losing_day=False)
    assert amount==.01
    assert 'M1' in sampling_policy(s)['name']
    s.practice_sampling_until=datetime(2020,1,1,tzinfo=timezone.utc)
    assert sampling_policy(s)['risk_cap']==.01
    assert sampling_policy(s)['cost_stop_fraction']==.25


def test_sampling_cannot_exceed_authorized_one_percent():
    with pytest.raises(ValueError): settings(practice_sampling_risk_cap=.011)
