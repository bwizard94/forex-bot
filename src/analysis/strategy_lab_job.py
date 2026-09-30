"""Run research out of process, with bounded runtime and no broker operations."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from src.analysis.documentation import atomic_write
from src.analysis.strategy_lab import LAB, ROOT


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
