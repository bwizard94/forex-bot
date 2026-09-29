from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.data.storage import Base, Trade, TradeJournal
from src.analysis.documentation import export_documents, read_documentation


def test_journal_outcomes_revision_history_and_ownership(tmp_path):
    engine=create_engine('sqlite:///:memory:'); Base.metadata.create_all(engine)
    (tmp_path/'OPERATING.md').write_text('Rules')
    with Session(engine) as s:
        journals=[]
        for i,(source,outcome,pl) in enumerate([('bot','win',10),('bot','loss',-5),('human','scratch',0)]):
            t=Trade(symbol='EUR/USD',side='BUY',units=100,requested_entry=1.1,
                    stop_loss=1.099,take_profit_1=1.101,take_profit_2=1.102,
                    broker_take_profit=1.102,status='closed',source=source,venue='oanda')
            s.add(t);s.flush()
            j=TradeJournal(trade_id=t.id,symbol='EUR/USD',side='BUY',outcome=outcome,
                           realized_pl=pl,entry_thesis='Setup',lesson='Review costs',
                           what_went_right='Protected entry',what_went_wrong='Not proven',how_to_avoid='Test timing')
            s.add(j);journals.append(j)
        s.commit()
        first=export_documents(s,tmp_path)
        assert first['journals']==3 and first['new_revisions']==3
        assert export_documents(s,tmp_path)['new_revisions']==0
        journals[1].lesson='Revised observation';s.commit()
        assert export_documents(s,tmp_path)['new_revisions']==1
        assert len(list((tmp_path/'journal/revisions').glob('*.md')))==4
        index=(tmp_path/'journal/INDEX.md').read_text()
        assert 'human / oanda' in index and 'win' in index and 'loss' in index
        body=(tmp_path/'journal/trade-2.md').read_text()
        assert 'Revised observation' in body and 'What went right' in body
        assert 'What went wrong' in body and 'Improvement to investigate' in body
        assert 'OPERATING.md' in (tmp_path/'INDEX.md').read_text()
    engine.dispose()


def test_document_reads_detect_changes_and_missing_files(tmp_path):
    p=tmp_path/'OPERATING.md';p.write_text('first')
    before=read_documentation(tmp_path)
    p.write_text('second')
    after=read_documentation(tmp_path)
    assert before['documents'][0]['sha256']!=after['documents'][0]['sha256']
    assert any(d.get('missing') for d in after['documents'])
