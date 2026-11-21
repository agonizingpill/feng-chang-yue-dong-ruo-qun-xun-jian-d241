import json
import os
import traceback
from pathlib import Path

import redis
from sqlalchemy import select

from .database import Session
from .models import Visit, Hive
from .screen_model import reference_model, screen
from .batch_service import apply_reading_screen, finish_screen
from .yard_service import latest

queue = redis.Redis.from_url(os.getenv('REDIS_URL', 'redis://redis:6379/0'), decode_responses=True)
ARTIFACTS = Path(os.getenv('ARTIFACTS_DIR', '/artifacts'))


def _write_artifact(name, result):
    try:
        ARTIFACTS.mkdir(exist_ok=True)
        (ARTIFACTS / name).write_text(json.dumps(result))
    except OSError:
        traceback.print_exc()


def run_visit_job(task):
    points = []
    evidence = reference_model()[1]
    try:
        for key in task['visit_ids']:
            Path('/tmp/apiary-heartbeat').touch()
            with Session() as db:
                visit = db.scalar(select(Visit).where(Visit.id == key).with_for_update())
                if not visit or visit.status != 'screening':
                    continue
                score, flag, margin, evidence = screen(visit)
                visit.anomaly_score = score
                visit.anomaly_flag = flag
                visit.decision_margin = margin
                visit.model_evidence = evidence
                visit.status = 'screened'
                hive = db.get(Hive, visit.hive_id)
                if latest(db, hive.id) == visit.id:
                    hive.care_state = 'needs_care' if flag or not visit.queen_seen else 'observe'
                db.commit()
                points.append({'visit_id': visit.id, 'hive_id': hive.id, 'score': score, 'flag': flag})
        result = {'status': 'done', 'count': len(points), 'points': points, 'evidence': evidence}
        _write_artifact(f"screen-{task['job_id']}.json", result)
        queue.set('apiary:screen:' + task['job_id'], json.dumps(result), ex=86400)
    except Exception as error:
        traceback.print_exc()
        queue.set(
            'apiary:screen:' + task['job_id'],
            json.dumps({'status': 'failed', 'error': str(error)}),
            ex=86400,
        )
        with Session() as db:
            for visit in db.scalars(
                select(Visit).where(Visit.id.in_(task['visit_ids']), Visit.status == 'screening')
            ).all():
                visit.status = 'blocked'
            db.commit()


def run_batch_job(task):
    points = []
    errors = 0
    try:
        for key in task['reading_ids']:
            Path('/tmp/apiary-heartbeat').touch()
            with Session() as db:
                try:
                    point = apply_reading_screen(db, key)
                    if point:
                        db.commit()
                        points.append(point)
                    else:
                        db.rollback()
                except Exception:
                    db.rollback()
                    errors += 1
                    traceback.print_exc()
        with Session() as db:
            if not points:
                finish_screen(
                    db,
                    task['batch_id'],
                    points,
                    error=RuntimeError(f'{len(task["reading_ids"])} 条封存读数均未能筛查'),
                )
            else:
                finish_screen(db, task['batch_id'], points)
            db.commit()
        if not points:
            raise RuntimeError('封存读数均未能筛查，可重新发起')
        result = {
            'status': 'done',
            'count': len(points),
            'points': points,
            'batch_id': task['batch_id'],
            'errors': errors,
        }
        _write_artifact(f"batch-screen-{task['job_id']}.json", result)
        queue.set('apiary:batch-screen:' + task['job_id'], json.dumps(result), ex=86400)
    except Exception as error:
        traceback.print_exc()
        queue.set(
            'apiary:batch-screen:' + task['job_id'],
            json.dumps({'status': 'failed', 'error': str(error), 'batch_id': task['batch_id']}),
            ex=86400,
        )
        with Session() as db:
            finish_screen(db, task['batch_id'], points, error=error)
            db.commit()


def main():
    while True:
        Path('/tmp/apiary-heartbeat').touch()
        job = queue.blpop(['apiary:screening', 'apiary:batch-screen'], timeout=3)
        if not job:
            continue
        channel, raw = job
        task = json.loads(raw)
        if channel == 'apiary:batch-screen':
            run_batch_job(task)
        else:
            run_visit_job(task)


if __name__ == '__main__':
    main()
