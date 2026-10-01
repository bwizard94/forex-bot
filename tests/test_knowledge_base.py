import json
from datetime import datetime,timezone,timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.data.storage import Base,Trade,TradeJournal
from src.analysis.knowledge_base import compile_knowledge


def test_hourly_compiler_preserves_revisions_excludes_mirrors_and_deduplicates(tmp_path):
    engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
    desk=tmp_path/'desk';desk.mkdir();lab=tmp_path/'lab';lab.mkdir()
    (desk/'OPERATING.md').write_text('Rules')
    (lab/'latest.json').write_text(json.dumps({'status':'collecting','evaluated_at':'first'}))
    now=datetime(2026,9,29,17,tzinfo=timezone.utc)
    with Session(engine) as s:
        for source,venue in [('bot','oanda'),('human','oanda'),('bot','mt4')]:
            t=Trade(symbol='EUR/USD',side='BUY',units=1,requested_entry=1.1,stop_loss=1.,take_profit_1=1.2,take_profit_2=1.3,broker_take_profit=1.3,status='closed',source=source,venue=venue,realized_pl=-1)
            s.add(t);s.flush();s.add(TradeJournal(trade_id=t.id,symbol='EUR/USD',side='BUY',lesson='Check entry cost',outcome='loss'))
        s.commit()
        first=compile_knowledge(s,desk,lab,now)
        assert first['changed']==5
        same=compile_knowledge(s,desk,lab,now)
        assert same['changed']==0
        assert len(list((desk/'knowledge/hourly').glob('*.json')))==1
        assert len(list((desk/'knowledge/revisions').glob('*.json')))==1
        (lab/'latest.json').write_text(json.dumps({'status':'collecting','evaluated_at':'later'}))
        assert compile_knowledge(s,desk,lab,now+timedelta(hours=1))['changed']==0
        (desk/'OPERATING.md').write_text('Revised rules')
        revised=compile_knowledge(s,desk,lab,now+timedelta(hours=2))
        assert revised['changed']==1 and revised['sha256']!=first['sha256']
        entries=json.loads((desk/'knowledge/current.json').read_text())['entries']
        assert entries['research:knowledge_gaps']['local_closed_primary_bot_trades']==1
        assert entries['research:knowledge_gaps']['missing']['original_risk']==1
        assert 'trade:1' in entries and 'trade:2' not in entries and 'trade:3' not in entries
        assert len(list((desk/'knowledge/revisions').glob('*.json')))==2
