"""Bounded, independently locked reporting workers; no broker clients."""
import fcntl
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from src.analysis.documentation import atomic_write

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT/'data/research/diagnostics'


def compact_diagnostics(diagnostics):
    """Keep counters and top reasons in status; the full report retains evidence."""
    result = dict(diagnostics)
    for key in ('hold_reasons', 'rejections', 'all_failed_checks'):
        values = result.get(key)
        if isinstance(values, dict):
            ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
            result[key] = dict(ordered[:10])
            result[key+'_distinct'] = max(len(values), result.get(key+'_distinct', 0))
            result[key+'_omitted_count'] = result.get(key+'_omitted_count', 0) + sum(v for _,v in ordered[10:])
    return result


from functools import lru_cache
from copy import deepcopy


@lru_cache(maxsize=32)
def _status_file(path, signature):
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError('Status must be an object')
    # Also compact old on-disk status without rewriting historical artifacts.
    if isinstance(payload.get('summary'), list):
        for row in payload['summary']:
            if isinstance(row, dict) and isinstance(row.get('rejections'), dict):
                row['rejections'] = compact_diagnostics(row['rejections'])
    return payload


def read_status(directory=REPORTS):
    result = {}
    for kind in ('attribution', 'costs', 'experiments', 'excursions', 'market', 'paired'):
        try:
            path = directory/f'{kind}-status.json'
            stat = path.stat()
            result[kind] = deepcopy(_status_file(str(path.resolve()),
                (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)))
            stamp=result[kind].get('finished_at') or result[kind].get('started_at')
            if stamp:
                ts=datetime.fromisoformat(stamp)
                if ts.tzinfo is None: raise ValueError('Timezone required')
                age=(datetime.now(timezone.utc)-ts).total_seconds()
                result[kind]['age_seconds']=max(0,round(age))
                running=result[kind].get('state')=='running'
                limit=(240 if kind=='attribution' else 1020) if running else (25200 if kind=='costs' else 7200)
                if kind=='excursions':limit=90
                if kind=='market':limit=1800
                if age>limit: result[kind]['stale']=True
        except FileNotFoundError:
            result[kind] = {'state': 'not_run'}
        except (OSError, ValueError, TypeError):
            result[kind] = {'state': 'unavailable', 'note': 'Status unreadable; availability is not confirmed.'}
    return result


def run_report(kind, settings=None, directory=REPORTS):
    if kind not in {'attribution', 'costs', 'experiments', 'paired'}:
        raise ValueError('Unknown report kind')
    from src.config import get_settings
    from src.analysis.research_settings import freeze_settings
    settings = settings or get_settings()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/f'{kind}.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'state':'already_running'}
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
        output = directory/f'{kind}-{run_id}.json'
        status = {'state':'running','started_at':datetime.now(timezone.utc).isoformat(),
                  'report':str(output),'validated_for_live':False}
        detail = ''
        def publish():
            atomic_write(directory/f'{kind}-status.json', json.dumps(status,indent=2))
            atomic_write(ROOT/'desk'/f'DIAGNOSTIC_{kind.upper()}.md',
                '# '+kind.title()+' diagnostic\n\n'+json.dumps(status,indent=2)+'\n\nResearch only; no execution authority.\n'+detail)
        publish()
        try:
            from sqlalchemy.engine import make_url
            url = make_url(settings.database_url)
            if url.get_backend_name() != 'sqlite' or not url.database or url.database == ':memory:':
                raise ValueError('Diagnostics require a file-backed SQLite database')
            database = Path(url.database).resolve()
            module = {'attribution':'src.analysis.learning_report','costs':'src.analysis.cost_stress','experiments':'src.analysis.policy_experiments','paired':'src.analysis.paired_study'}[kind]
            command = [sys.executable,'-m',module,'--database',str(database),'--output',str(output)]
            if kind=='costs':
                run_market_archive()
                try:
                    subprocess.run([sys.executable,'-m','src.analysis.broker_cost_profile'],cwd=ROOT,timeout=45,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
                except (OSError,subprocess.SubprocessError):
                    status['broker_cost_refresh']='failed; archived profile or explicit unknown reference retained'
            if kind!='attribution':
                from src.analysis.execution_assumptions import archived_assumptions
                assumptions_path=directory/f'assumptions-{run_id}.json'
                assumptions=archived_assumptions(directory)
                if kind=='costs':
                    from src.analysis.measured_archive import load
                    market=load()
                    if not market:raise ValueError('Measured market archive unavailable')
                    assumptions.update(market_bars=market,market_timeframe='M1')
                    assumptions['provenance']+='; measured_completed_bid_ask'
                atomic_write(assumptions_path,json.dumps(assumptions,indent=2))
                if kind=='costs':command += ['--assumptions',str(assumptions_path)]
                snapshot=directory/f'configuration-{run_id}.json'
                atomic_write(snapshot,json.dumps(freeze_settings(settings,origin='active_process_allowlist'),indent=2))
                command += ['--settings-snapshot',str(snapshot)]
            subprocess.run(command,cwd=ROOT,timeout=900 if kind!='attribution' else 120,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
            payload=json.loads(output.read_text())
            status.update(state='complete', finished_at=datetime.now(timezone.utc).isoformat())
            if kind=='attribution':
                context=payload['contextual_attribution']
                loss=payload.get('loss_attribution',{})
                loss_lines=['\nRollback watch (advisory): '+str(loss.get('rollback_watch',{}))+'\n', '\n## Where losses accumulate\n', '| Dimension | Value | Trades | Price P/L | Mean R |', '| --- | --- | ---: | ---: | ---: |']
                for row in sorted(loss.get('groups',[]),key=lambda r:r['all']['net_pl']):
                    m=row['all'];loss_lines.append(f"| {row['dimension']} | {row['value']} | {m['samples']} | {m['net_pl']} | {m['mean_r']} |")
                comparisons=context.get('comparisons',[])
                detail='\n## Matched version comparisons\n\n| Context | A version / config | B version / config | R samples A/B | Mean R B minus A | Evidence |\n| --- | --- | --- | ---: | ---: | --- |\n'
                for pair in comparisons:
                    a,b=pair['a'],pair['b']
                    detail+=f"| {pair['context']} | {a['code_sha256'][:12]} / {a['configuration_sha256'][:12]} | {b['code_sha256'][:12]} / {b['configuration_sha256'][:12]} | {a['performance']['r_samples']}/{b['performance']['r_samples']} | {pair['mean_r_difference_b_minus_a']} | {pair['evidence_status']} |\n"
                if not comparisons: detail+='\nNo versions have comparable recorded contexts yet.\n'
                detail+='\nDifferences are descriptive; date and cost differences remain confounders. No automatic winner or promotion.\n'
                detail+='\n'.join(loss_lines)+'\nDimensions overlap; compare winners and losers in the JSON artifact. Associations are not causes.\n'
                detail+='\n## Individual trade assessments\n'
                for item in payload.get('individual_reviews',[]):
                    assessment=item['assessment']
                    detail+=f"\n### Trade {item['trade_id']}\n"
                    for key,label in (('facts','Observed'),('hypotheses_to_test','Test'),('unknowns','Unknown')):
                        detail+=''.join(f'- {label}: {value}\n' for value in assessment[key])
                status['summary']={'closed_trades':context['closed_trades'],'groups':len(context['groups']),
                                   'comparisons':len(context.get('comparisons',[]))}
            elif kind in {'experiments','paired'}:
                status['summary']={k:v for k,v in payload.items() if k not in {'runs','chunks'}}
            else:
                status['summary']=[{'scenario':r['scenario'],'metrics':r['completed_metrics'],
                                    'rejections':compact_diagnostics(r.get('diagnostics',{}))} for r in payload['runs']]
        except Exception as exc:
            status.update(state='failed',finished_at=datetime.now(timezone.utc).isoformat(),
                          error=type(exc).__name__, note='Report failed or timed out; prior reports retained.')
        publish()
        return status


def archive_calendar(pipeline, directory=REPORTS):
    """Capture already-fetched events, never backdate when the bot knew them."""
    import hashlib
    bundle=getattr(pipeline.news, '_bundle', None)
    if bundle is None: return
    now=datetime.now(timezone.utc).isoformat()
    events=[{'title':e.title,'currency':e.country,'impact':e.impact,
             'ts':e.ts.isoformat(),'known_at':now} for e in bundle.events if e.ts is not None]
    digest=hashlib.sha256(json.dumps([{k:v for k,v in e.items() if k!='known_at'} for e in events],sort_keys=True).encode()).hexdigest()
    folder=directory/'calendar';folder.mkdir(parents=True,exist_ok=True)
    # Retain each distinct observed version; reads use known_at to avoid hindsight.
    path=folder/f'{digest}.json'
    if not path.exists(): atomic_write(path,json.dumps(events))


def run_market_archive():
    REPORTS.mkdir(parents=True,exist_ok=True)
    with (REPORTS/'market.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'state':'already_running'}
        status={'state':'running','started_at':datetime.now(timezone.utc).isoformat()}
        atomic_write(REPORTS/'market-status.json',json.dumps(status))
        try:
            subprocess.run([sys.executable,'-m','src.analysis.measured_archive'],cwd=ROOT,
                           timeout=120,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except (OSError,subprocess.SubprocessError) as exc:
            status.update(state='failed',finished_at=datetime.now(timezone.utc).isoformat(),error=type(exc).__name__)
            atomic_write(REPORTS/'market-status.json',json.dumps(status))
        return json.loads((REPORTS/'market-status.json').read_text())
