import json
from src.analysis.strategy_lab_job import read_learning_status


def test_archived_experiments_do_not_claim_completed_evidence(tmp_path):
    (tmp_path/'latest.json').write_text(json.dumps({'status':'collecting_prospective_evidence','completed_experiments':4}))
    (tmp_path/'controller.json').write_text(json.dumps({'history':[
        {'reason':'source_changed','status':'collecting_prospective_evidence'},
        {'reason':'insufficient_evidence_at_deadline','status':'collecting_prospective_evidence'},
        {'reason':'completed','status':'all_candidates_rejected'},
        {'reason':'completed','status':'forward_review_required'},
    ]}))
    result=read_learning_status(tmp_path)
    assert result['completed_experiments']==2
    assert result['invalidated_experiments']==1
    assert result['archived_experiments']==4


def test_unverifiable_count_is_unknown_not_old_claim(tmp_path):
    (tmp_path/'latest.json').write_text(json.dumps({'completed_experiments':2}))
    assert read_learning_status(tmp_path)['completed_experiments'] is None
