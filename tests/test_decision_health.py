from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.data.storage import Base, insert_signal
from src.analysis.decision_health import decision_health
from test_growth import _signal


def test_recent_unique_live_bars_and_blockers():
    engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
    now=datetime.now(timezone.utc)
    with Session(engine) as session:
        for age, action, source, reason in [(5,'SELL','live','Cost: spread'),
                (10,'BUY','live','Entry quality: price moved'),(15,'HOLD','live',None),
                (20,'SELL','history','Cost: spread'),(1500,'SELL','live','Cost: spread')]:
            row=_signal(timestamp=now-timedelta(minutes=age),action=action).to_row(skipped=bool(reason),skip_reason=reason)
            row['source']=source; insert_signal(session,row)
        session.flush()
        result=decision_health(session,now)
        assert result['unique_bar_decisions']==3
        assert result['directional_setups']==2 and result['holds']==1
        assert result['blocked_setups']==2
        assert {r['reason'] for r in result['blockers']}=={'Spread/cost','Entry price/quality'}
    engine.dispose()
