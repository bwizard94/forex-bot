"""Read-only SQLite learning audit. No broker clients, migrations or rule updates."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from src.analysis.growth import study_book
from src.config import Settings
from src.data.storage import DecisionObservation


def report_database(path: Path) -> dict:
    # mode=ro refuses nonexistent files and prevents accidental database writes.
    uri = path.resolve().as_uri() + '?mode=ro'
    engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(uri, uri=True))
    try:
        with Session(engine) as session:
            report = study_book(session, settings=Settings()).as_dict()
            reasons = Counter()
            versions = Counter()
            actions = Counter()
            observations = 0
            if 'decision_observations' in inspect(engine).get_table_names():
                rows = session.scalars(select(DecisionObservation).where(
                    DecisionObservation.symbol == 'EUR/USD')).yield_per(500)
                for row in rows:
                    observations += 1
                    payload = row.payload
                    actions[payload.get('action') or 'unknown'] += 1
                    if payload.get('skipped'):
                        reasons[payload.get('skip_reason') or 'unspecified'] += 1
                    evidence = payload.get('decision_context') or {}
                    versions[evidence.get('code_sha256') or 'unknown'] += 1
            report['decision_observations'] = {
                'count': observations, 'actions': dict(actions),
                'skip_reasons': dict(reasons), 'code_versions': dict(versions),
            }
            report['limitations'] = [
                'Repeated evaluations of one candle count as separate observations, not independent trades.',
                'R uses recorded realized P/L; full commission/financing reconciliation is not certified.',
                'Legacy trades lacking entry-time risk are excluded from R, not reconstructed.',
                'Statistics are descriptive; no strategy promotion, risk increase or profitability claim.',
            ]
            return report
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path, help='Existing SQLite database path')
    parser.add_argument('--output', type=Path, help='New JSON path; never overwrites')
    args = parser.parse_args()
    try:
        payload = json.dumps(report_database(args.database), indent=2, allow_nan=False) + '\n'
        if args.output:
            with args.output.open('x', encoding='utf-8') as handle:
                handle.write(payload)
        else:
            print(payload, end='')
    except (OSError, ValueError, SQLAlchemyError) as exc:
        parser.exit(2, f'Learning audit failed: {exc}\n')


if __name__ == '__main__':
    main()
