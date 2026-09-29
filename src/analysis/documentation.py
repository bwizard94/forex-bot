"""Indexed desk documents and reproducible journals from committed trade records."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from sqlalchemy import select
from src.data.storage import Trade, TradeJournal

DESK = Path(__file__).resolve().parents[2] / 'desk'
LOCK = Lock()
READING = ('OPERATING.md', 'SCALPING.md', 'MISTAKES.md', 'MT4.md',
           'GROWTH.md', 'LEARNING_LOG.md', 'journal/INDEX.md',
           'STRATEGY_LAB.md', 'STRATEGY_LEARNING_STATUS.md', 'KNOWLEDGE_BASE.md')


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as out:
        out.write(text)
        temporary = Path(out.name)
    temporary.replace(path)


def read_documentation(desk=DESK):
    documents = []
    for name in READING:
        try:
            content = (desk / name).read_bytes()
            documents.append({'path': name, 'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)})
        except OSError:
            documents.append({'path': name, 'missing': True})
    return {'read_at': datetime.now(timezone.utc).isoformat(), 'documents': documents,
            'role': 'Reference and evidence; prose does not override deterministic trading rules.'}


def render_trade(trade, journal):
    from src.analysis.loss_review import review_loss
    def text(value):
        return str(value) if value is not None and value != '' else 'Not recorded.'
    sections = [('Entry thesis', journal.entry_thesis), ('Exit assessment', journal.exit_verdict),
                ('What went right', journal.what_went_right), ('What went wrong', journal.what_went_wrong),
                ('Recorded lesson', journal.lesson), ('Improvement to investigate', journal.how_to_avoid)]
    lines = [f'# Trade {trade.id} — {trade.symbol} {trade.side}', '',
             f'Ownership: **{trade.source}** · Venue: **{trade.venue}** · Status: **{trade.status}**',
             f'Broker trade reference: {text(trade.broker_trade_id)}',
             f'Opened: {text(trade.opened_at)} · Closed: {text(trade.closed_at)}',
             f'Journal outcome: **{journal.outcome}** · Recorded price P/L: **{journal.realized_pl}**',
             f'Exit reason: {text(journal.close_reason)} · Hold minutes: {text(journal.hold_minutes)}', '',
             'Recorded P/L is not an all-cost return. Financing is separate. Human and mirrored trades are not primary bot performance.', '',
             'Assessments below are deterministic journal interpretations, not proof of causation or a validated improvement. Missing fields are left unknown.']
    for heading, value in sections:
        lines.extend(['', f'## {heading}', '', text(value)])
    if journal.outcome == 'loss':
        review = review_loss(trade, journal)
        lines.extend(['', '## Contextual loss assessment', '',
                      'Historical lesson text above may describe older bans. Outcome-only bans are advisory when practice contextual review is enabled.',
                      *('- Fact: '+v for v in review['facts']),
                      *('- Test: '+v for v in review['hypotheses_to_test']),
                      *('- Unknown: '+v for v in review['unknowns']), review['recommendation']])
    context = journal.entry_context or {}
    risk = context.get('initial_risk') or {}
    policy = (context.get('decision_evidence') or {}).get('sampling_policy') or {}
    lines.extend(['', '## Trading policy', '', f'Policy: {policy.get("name", "Not recorded")}',
                  f'Trial status at decision: {policy.get("status", "Not recorded")}',
                  'Compare trial outcomes separately from baseline outcomes; additional trades are not proof of improvement.'])
    lines.extend(['', '## Evidence and next review', '',
                  f'Initial-risk basis: {text(risk.get("basis"))}',
                  f'Setup fingerprint: {text(journal.fingerprint)}',
                  'Compare the proposed improvement across similar setups and unseen periods after costs before changing live rules.',
                  'Source: committed trades and trade_journals database records. This file is generated; keep manual notes separately.', ''])
    return '\n'.join(lines)


def export_documents(session, desk=DESK):
    with LOCK:
        rows = session.execute(select(Trade, TradeJournal).join(TradeJournal, TradeJournal.trade_id == Trade.id)
                               .where(Trade.symbol == 'EUR/USD').order_by(Trade.id)).all()
        index = ['# Trading journey', '', 'Generated from committed records. Separate bot, human and mirrored venue results.', '',
                 '| Trade | Ownership / venue | Status | Outcome | Price P/L | Journal |',
                 '| --- | --- | --- | --- | ---: | --- |']
        created = 0
        for trade, journal in rows:
            body = render_trade(trade, journal)
            digest = hashlib.sha256(body.encode()).hexdigest()
            name = f'trade-{trade.id}.md'
            revision = desk / 'journal' / 'revisions' / f'trade-{trade.id}-{digest}.md'
            if not revision.exists():
                atomic_write(revision, body)
                created += 1
            current = desk / 'journal' / name
            if not current.exists() or current.read_text() != body:
                atomic_write(current, body)
            index.append(f'| {trade.id} | {trade.source} / {trade.venue} | {trade.status} | {journal.outcome} | {journal.realized_pl} | [{name}]({name}) |')
        index.extend(['', '[Daily activity and lessons](daily/INDEX.md)', '', 'Revisions are preserved in [revisions/](revisions/); identical content does not create duplicate versions.', ''])
        atomic_write(desk / 'journal/INDEX.md', '\n'.join(index))
        catalog = ['# Desk documentation index', '',
                   'Start with the operating rules, then review the current book and individual trade journals. Existing paths are preserved.', '',
                   '## Operating rules', '']
        core = {'OPERATING.md', 'SCALPING.md', 'MISTAKES.md', 'MT4.md'}
        live = {'EURUSD_PLAYBOOK.md', 'GROWTH.md', 'HISTORY.md', 'LEARNING_LOG.md', 'NEWS_LOG.md', 'NEWS_PATTERNS.md'}
        files = {p.name for p in desk.glob('*.md')} - {'INDEX.md'}
        for label, names in [('rules', files & core), ('Current book and learning', files & live),
                             ('Research, integrations, setup and audits', files-core-live)]:
            if label != 'rules': catalog.extend(['', '## '+label, ''])
            catalog.extend(f'- [{name}]({name})' for name in sorted(names))
        catalog.extend(['', '## Individual trade journals', '', '- [Trading journey](journal/INDEX.md)', '',
                        'Do not edit generated journals: use a separate manual notes document. Prose lessons are proposals, not authorization to alter trading rules.', ''])
        atomic_write(desk / 'INDEX.md', '\n'.join(catalog))
        from src.analysis.daily_journey import render_daily_journey
        today = datetime.now(timezone.utc).date()
        for day in (today - timedelta(days=1), today):
            path = desk / 'journal/daily' / f'{day.isoformat()}.md'
            body = render_daily_journey(session, day)
            if not path.exists() or path.read_text() != body:
                atomic_write(path, body)
        daily_files = sorted((desk / 'journal/daily').glob('????-??-??.md'), reverse=True)
        atomic_write(desk / 'journal/daily/INDEX.md', '# Daily trading journey\n\n' +
                     '\n'.join(f'- [{p.stem}]({p.name})' for p in daily_files) + '\n')
        receipt = read_documentation(desk)
        atomic_write(desk / 'DOCUMENT_ACCESS.json', json.dumps(receipt, indent=2)+'\n')
        return {'ok': True, 'exported_at': datetime.now(timezone.utc).isoformat(),
                'journals': len(rows), 'new_revisions': created, 'documentation': receipt}
