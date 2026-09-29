from unittest.mock import Mock
from types import SimpleNamespace
from src.pipeline import TradingPipeline
from src import main


def test_failure_does_not_prevent_remaining_startup_tasks():
    p=TradingPipeline.__new__(TradingPipeline)
    p.run_cycle=Mock(return_value={'status':'error'})
    p._maybe_catchup_desk_notes=Mock(side_effect=RuntimeError('optional failure'))
    p.kick_sheets_sync=Mock(return_value=False)
    p.send_tape_pulse=Mock()
    p.run_intel=Mock()
    p.kick_history_study=Mock(return_value=True)
    p.run_startup_tasks()
    assert p.startup_tasks['state']=='degraded'
    assert p.startup_tasks['failed']==['initial_scan','desk_notes']
    assert p.startup_tasks['completed']==['sheets','tape','intel','history']
    assert p.startup_tasks['current'] is None
    p.kick_history_study.assert_called_once()


def test_dashboard_starts_without_waiting_for_enrichment(monkeypatch):
    p=Mock()
    scheduler=Mock()
    monkeypatch.setattr(main,'get_pipeline',lambda:p)
    monkeypatch.setattr(main,'get_settings',lambda:SimpleNamespace(log_level='INFO',dashboard_host='127.0.0.1',dashboard_port=8765))
    monkeypatch.setattr(main,'setup_logging',lambda _:None)
    monkeypatch.setattr(main,'_build_scheduler',lambda _:scheduler)
    def serve(*args,**kwargs):
        p.startup.assert_called_once()
        p.run_cycle.assert_not_called()
        p.run_startup_tasks.assert_not_called()
        scheduler.start.assert_called_once()
        assert scheduler.add_job.call_args_list[0].args==(p.run_startup_tasks,'date')
        assert scheduler.add_job.call_args_list[1].args==(p.refresh_documentation,'interval')
    monkeypatch.setattr(main.uvicorn,'run',serve)
    main._run()
    p.set_trading.assert_not_called()
    scheduler.shutdown.assert_called_once_with(wait=False)
    p.shutdown.assert_called_once()
