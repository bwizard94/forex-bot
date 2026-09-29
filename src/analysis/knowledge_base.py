"""Hourly evidence compilation; statements are recorded lessons, not trading rules."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from loguru import logger
from sqlalchemy import select
from src.analysis.documentation import DESK, atomic_write
from src.data.storage import Trade, TradeJournal, session_scope

LOCK = Lock()
LAB = Path(__file__).resolve().parents[2]/'data/research/strategy-lab'


def compile_knowledge(session, desk=DESK, lab=LAB, now=None):
    now=now or datetime.now(timezone.utc)
    entries={}
    rows=session.execute(select(Trade,TradeJournal).join(TradeJournal,TradeJournal.trade_id==Trade.id)
        .where(Trade.symbol=='EUR/USD',Trade.source=='bot',Trade.venue=='oanda',
               Trade.parent_trade_id.is_(None),Trade.status=='closed')).all()
    for t,j in rows:
        from src.analysis.loss_review import review_loss
        entries[f'trade:{t.id}']={'type':'recorded_trade_lesson','source':f'journal/trade-{t.id}.md',
            'price_pl':str(t.realized_pl),'closed_at':str(t.closed_at),'outcome':j.outcome,
            'went_right':j.what_went_right,'went_wrong':j.what_went_wrong,
            'lesson':j.lesson,'improvement_to_test':j.how_to_avoid,
            'contextual_review':review_loss(t,j),
            'evidence_label':'Recorded interpretation; causation and improvement unproven; historical ban recommendations are not current execution instructions'}
    for path in sorted(desk.glob('*.md')):
        if path.name in {'KNOWLEDGE_BASE.md','INDEX.md','STRATEGY_LEARNING_STATUS.md'}:
            continue
        data=path.read_bytes()
        entries[f'document:{path.name}']={'type':'reference_document','source':path.name,
            'sha256':hashlib.sha256(data).hexdigest(),
            'evidence_label':'Reference or research; consult source limitations'}
    for name in ('controller.json','latest.json'):
        path=lab/name
        if not path.exists():continue
        data=json.loads(path.read_text())
        if name=='controller.json':
            for record in data.get('history',[]):
                entries[f'experiment:{record["experiment_id"]}']={'type':'research_outcome',
                    'source':str(path),'result':record,'evidence_label':'Simulation only; no broker promotion'}
        else:
            entries['research:current']={'type':'research_status','source':str(path),
                'status':data.get('status'),'generation':data.get('generation'),
                'candidates':data.get('candidates',[]),'validated_for_live':False}
    folder=desk/'knowledge';folder.mkdir(parents=True,exist_ok=True)
    previous=json.loads((folder/'current.json').read_text()) if (folder/'current.json').exists() else {'entries':{}}
    changed={k:v for k,v in entries.items() if previous['entries'].get(k)!=v}
    removed=sorted(set(previous['entries'])-set(entries))
    digest=hashlib.sha256(json.dumps(entries,sort_keys=True).encode()).hexdigest()
    report={'compiled_at':now.isoformat(),'sha256':digest,'entries':entries,
            'changed_entries':list(changed),'removed_entries':removed,'validated_for_live':False}
    # A content-addressed revision preserves corrections; hourly reports record checks.
    if not (folder/'revisions'/f'{digest}.json').exists():
        atomic_write(folder/'revisions'/f'{digest}.json',json.dumps(report,indent=2)+'\n')
    atomic_write(folder/'current.json',json.dumps(report,indent=2)+'\n')
    hour=now.strftime('%Y%m%dT%H')
    hourly=folder/'hourly'/f'{hour}-{digest}.json'
    if not hourly.exists():
        atomic_write(hourly,json.dumps({'compiled_at':now.isoformat(),'changes':changed,'removed':removed,
                                      'revision':digest,'no_new_evidence':not changed and not removed},indent=2)+'\n')
    lines=['# Compiled knowledge base','',f'Last compiled: {now.isoformat()}',
           f'New or revised entries this check: {len(changed)}. Current entries: {len(entries)}.','',
           'Recorded outcomes, research and hypotheses are separate. This compilation does not change entry rules or risk.', '',
           '## Trade lessons','']
    for key,item in entries.items():
        if item['type']=='recorded_trade_lesson':
            lines.extend([f'### [{key}]({item["source"]})',f'Price P/L: {item["price_pl"]}; outcome: {item["outcome"]}',
                f'Went right: {item["went_right"] or "Not recorded"}',f'Went wrong: {item["went_wrong"] or "Not recorded"}',
                f'Lesson: {item["lesson"] or "Not recorded"}',f'Test next: {item["improvement_to_test"] or "Not recorded"}',''])
            lines.extend(['Contextual review (historical ban advice is not an execution instruction):',
                          *('- '+v for v in item['contextual_review']['facts']),
                          *('- Investigate: '+v for v in item['contextual_review']['hypotheses_to_test']),
                          *('- Unknown: '+v for v in item['contextual_review']['unknowns']), ''])
    lines.extend(['## Research evidence','',json.dumps({k:v for k,v in entries.items() if k.startswith(('research:','experiment:'))},indent=2),'',
                  '## Reference documents',''])
    lines.extend(f'- [{v["source"]}]({v["source"]})' for v in entries.values() if v['type']=='reference_document')
    lines.extend(['','Hourly changes: `knowledge/hourly/`. Versioned evidence: `knowledge/revisions/`.',''])
    atomic_write(desk/'KNOWLEDGE_BASE.md','\n'.join(lines))
    status={'ok':True,'compiled_at':now.isoformat(),'entries':len(entries),'changed':len(changed),'sha256':digest}
    atomic_write(folder/'status.json',json.dumps(status)+'\n')
    return status


def run_knowledge_job():
    with LOCK:
        try:
            with session_scope() as session:
                return compile_knowledge(session)
        except Exception:
            atomic_write(DESK/'knowledge/status.json',json.dumps({'ok':False,
                'checked_at':datetime.now(timezone.utc).isoformat(),'error':'Compilation failed; last successful knowledge retained'})+'\n')
            logger.exception('Hourly knowledge compilation failed')
