"""Run research out of process, with bounded runtime and no broker operations."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from src.analysis.documentation import atomic_write
from src.analysis.strategy_lab import LAB, ROOT


def read_learning_status(directory=LAB):
    """Present archives separately from completed evaluations; preserve frozen workers."""
    from src.analysis.strategy_lab import read_status
    status = read_status(directory)
    try:
        history = json.loads((directory/'controller.json').read_text())['history']
        from src.analysis.continuous_lab import TERMINAL
        status.update({
            'archived_experiments': len(history),
            'completed_experiments': sum(h.get('reason') == 'completed' and h.get('status') in TERMINAL for h in history),
            'invalidated_experiments': sum(h.get('reason') == 'source_changed' for h in history),
        })
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        status['completed_experiments'] = None
        status['experiment_history_note'] = 'Completion count unavailable; archive history could not be verified.'
    return status


def run_lab_job():
    # Separate, bounded diagnostic process cannot stall the quote loop or prevent
    # the prospective experiment worker from running.
    try:
        subprocess.run([sys.executable, '-m', 'src.analysis.indicator_audit'],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=90, check=True)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        from src.analysis.indicator_audit import REPORT, save_report
        save_report({"status": "failed", "validated_for_live": False,
                     "evaluated_at": datetime.now(timezone.utc).isoformat()}, REPORT)
    try:
        completed = subprocess.run([sys.executable, '-m', 'src.analysis.continuous_lab'],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800,
            check=False)
        if completed.returncode:
            raise RuntimeError(f'research process exited {completed.returncode}')
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        # Never leave an old success looking current after a failed run.
        failure = json.dumps({
            'status':'evaluation_failed', 'validated_for_live':False,
            'evaluated_at':datetime.now(timezone.utc).isoformat(),
            'note':str(exc)})+'\n'
        atomic_write(LAB/'latest.json', failure)
        try:
            active=json.loads((LAB/'controller.json').read_text()).get('active_id')
            if active and '/' not in active and active not in {'.','..'}:
                atomic_write(LAB/'experiments'/active/'latest.json',failure)
        except (OSError, ValueError):
            pass
        atomic_write(ROOT/'desk/STRATEGY_LEARNING_STATUS.md',
                     '# Strategy learning status\n\nEvaluation failed. No strategy promotion.\n\n'+str(exc)+'\n')
