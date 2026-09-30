"""Evidence gate and immutable promotion/rollback plans; no broker write authority."""
import hashlib,json,math
from pathlib import Path
from src.analysis.documentation import atomic_write


def review(spec,result):
    reasons=[]
    from src.analysis.policy_experiments import hashes
    if spec['source_hashes']!=hashes():reasons.append('source_changed')
    if result.get('status')!='forward_review_required':reasons.append('prospective_tests_not_passed')
    if result.get('source_hashes')!=spec['source_hashes']:reasons.append('result_provenance_missing_or_changed')
    names={c['name'] for c in spec['candidates']}
    eligible=result.get('eligible',[])
    if not eligible or not set(eligible)<=names:reasons.append('no_verified_candidate')
    expected={(w,s) for w in range(3) for s in spec['spreads']}
    for name in eligible:
        runs=[r for r in result.get('runs',[]) if r.get('candidate')==name]
        if len(runs)!=len(expected) or {(r.get('window'),r.get('spread_pips')) for r in runs}!=expected or not all(r.get('assessment',{}).get('passed') for r in runs):
            reasons.append('incomplete_or_failed_windows')
    # Passing price-only simulations cannot certify account-cost implementation.
    if not result.get('execution_costs_verified',False):reasons.append('broker_cost_and_execution_validation_required')
    return {'state':'ready_for_controlled_forward_trial' if not reasons else 'not_eligible',
            'reasons':reasons,'eligible_candidates':result.get('eligible',[]),
            'automatic_execution_authority':False,'validated_for_live':False}


def rollback_assessment(rows):
    """Predeclared post-deployment monitoring: records must be from that version."""
    if len(rows)<20:return {'state':'collecting','required_trades':20}
    versions={r.get('policy_id') for r in rows}
    if None in versions or len(versions)!=1:return {'state':'review_required','reason':'mixed_or_missing_policy_lineage'}
    values=[r.get('realized_r') for r in rows]
    if any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in values):
        return {'state':'review_required','reason':'missing_original_risk'}
    running=peak=drawdown=0
    for value in values:
        running+=value;peak=max(peak,running);drawdown=max(drawdown,peak-running)
    return {'state':'rollback_review_required' if drawdown>=5 or sum(values[-20:])<=-3 else 'continue_monitoring',
            'max_drawdown_r':drawdown,'last20_r':sum(values[-20:]),'automatic_execution_authority':False}


def save_plan(spec,result,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    decision=review(spec,result)
    plan={'evidence_gate':decision,'previous_settings':spec['baseline'],
          'candidate_changes':spec['candidates'],'registration_sha256':hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest(),
          'rollback_policy':{'minimum_closed_trades':20,'max_drawdown_r':5,'last20_r_floor':-3},
          'execution_state':'unchanged','note':'Retain prior version. No broker settings are changed by this artifact.'}
    digest=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    path=directory/(digest+'.json')
    if not path.exists():
        with path.open('x') as out:json.dump(plan,out,indent=2)
    atomic_write(directory/'latest.json',json.dumps({'plan':str(path),'decision':decision},indent=2))
    return plan
