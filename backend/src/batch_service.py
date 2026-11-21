import hashlib
import json
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

from .models import CareAction, Hive, Visit
from .batch_models import InspectionBatch, InspectionBatchHive, InspectionReading
from .season_models import ApiaryMove
from .yard_service import audit

FIELDS = ['weight_kg', 'temperature', 'activity', 'feed_left', 'queen_seen', 'colony_frames']
FIELD_LABELS = {
    'weight_kg': '抬箱体重',
    'temperature': '箱温',
    'activity': '出入蜂活动',
    'feed_left': '余饲',
    'queen_seen': '巡检王况',
    'colony_frames': '蜂量框数',
}
ACTIVE_BATCH_STATES = ['claimed', 'received']
ACTIVE_CARE_STATES = ['planned', 'executed', 'rechecked']
RESCREEN_AFTER = timedelta(minutes=5)


def _now():
    return datetime.utcnow()


def _fingerprint(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _batch(db, key, lock=False):
    query = select(InspectionBatch).where(InspectionBatch.id == key)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(query)
    if not row:
        raise HTTPException(404, '巡检批次不存在')
    return row


def _roster(db, batch_id):
    return db.scalars(
        select(InspectionBatchHive)
        .where(InspectionBatchHive.batch_id == batch_id)
        .order_by(InspectionBatchHive.seq, InspectionBatchHive.id)
    ).all()


def _readings(db, batch_id):
    return db.scalars(
        select(InspectionReading)
        .where(InspectionReading.batch_id == batch_id)
        .order_by(InspectionReading.id)
    ).all()


def _complete_by_hive(db, batch_id):
    rows = db.scalars(
        select(InspectionReading).where(
            InspectionReading.batch_id == batch_id,
            InspectionReading.state.in_(['complete', 'accepted']),
        )
    ).all()
    return {row.hive_id: row for row in rows}


def _reading_view(reading):
    return {
        'id': reading.id,
        'hive_id': reading.hive_id,
        'hive_code': reading.hive_code,
        'weight_kg': reading.weight_kg,
        'temperature': reading.temperature,
        'activity': reading.activity,
        'feed_left': reading.feed_left,
        'queen_seen': reading.queen_seen,
        'colony_frames': reading.colony_frames,
        'state': reading.state,
        'missing_fields': reading.missing_fields or [],
        'note': reading.note,
        'conflict_note': reading.conflict_note,
        'recorded_by': reading.recorded_by,
        'recorded_at': reading.recorded_at,
        'visit_id': reading.visit_id,
        'anomaly_score': reading.anomaly_score,
        'anomaly_flag': reading.anomaly_flag,
        'decision_margin': reading.decision_margin,
        'model_evidence': reading.model_evidence,
    }


def progress(db, batch):
    roster = _roster(db, batch.id)
    readings = _readings(db, batch.id)
    complete = _complete_by_hive(db, batch.id)
    conflicts = [row for row in readings if row.state == 'conflict']
    # 缺项记录留在原批作证据，但该箱补成完整读数后不再算未完成缺项。
    incomplete = [
        row for row in readings if row.state == 'incomplete' and row.hive_id not in complete
    ]
    missing = [h for h in roster if h.hive_id not in complete]
    return {
        'hive_count': len(roster),
        'complete_count': len(complete),
        'missing_count': len(missing),
        'incomplete_count': len(incomplete),
        'conflict_count': len(conflicts),
        'percent': round(len(complete) * 100 / len(roster), 1) if roster else 0,
        'missing': [{'hive_id': h.hive_id, 'hive_code': h.hive_code, 'site': h.site} for h in missing],
        'incomplete': [_reading_view(row) for row in incomplete],
        'conflicts': [_reading_view(row) for row in conflicts],
    }


def batch_view(db, batch):
    roster = _roster(db, batch.id)
    readings = _readings(db, batch.id)
    complete = _complete_by_hive(db, batch.id)
    readings_by_hive = {}
    for row in readings:
        readings_by_hive.setdefault(row.hive_id, []).append(row)
    hives = []
    for item in roster:
        rows = readings_by_hive.get(item.hive_id, [])
        primary = complete.get(item.hive_id)
        if primary is None:
            partial = [row for row in rows if row.state == 'incomplete']
            primary = partial[-1] if partial else (rows[-1] if rows else None)
        if item.hive_id in complete:
            status = 'complete'
        elif rows:
            status = 'partial'
        else:
            status = 'missing'
        hives.append(
            {
                'hive_id': item.hive_id,
                'hive_code': item.hive_code,
                'site': item.site,
                'seq': item.seq,
                'status': status,
                'reading': _reading_view(primary) if primary else None,
                'readings': [_reading_view(row) for row in rows],
            }
        )
    return {
        'id': batch.id,
        'code': batch.code,
        'state': batch.state,
        'note': batch.note,
        'claimed_by': batch.claimed_by,
        'claimed_at': batch.claimed_at,
        'parent_batch_id': batch.parent_batch_id,
        'received_by': batch.received_by,
        'received_at': batch.received_at,
        'sealed_by': batch.sealed_by,
        'sealed_at': batch.sealed_at,
        'seal_reason': batch.seal_reason,
        'seal_fingerprint': batch.seal_fingerprint,
        'seal_snapshot': batch.seal_snapshot,
        'screen_state': batch.screen_state,
        'screen_job_id': batch.screen_job_id,
        'screened_count': batch.screened_count,
        'screened_at': batch.screened_at,
        'cancelled_by': batch.cancelled_by,
        'cancelled_at': batch.cancelled_at,
        'cancel_reason': batch.cancel_reason,
        'hives': hives,
        'readings': [_reading_view(row) for row in readings],
        'progress': progress(db, batch),
        'next_action': next_action(batch),
    }


def batch_summary(db, batch):
    data = progress(db, batch)
    return {
        'id': batch.id,
        'code': batch.code,
        'state': batch.state,
        'note': batch.note,
        'claimed_by': batch.claimed_by,
        'claimed_at': batch.claimed_at,
        'received_by': batch.received_by,
        'received_at': batch.received_at,
        'sealed_by': batch.sealed_by,
        'sealed_at': batch.sealed_at,
        'seal_reason': batch.seal_reason,
        'seal_fingerprint': batch.seal_fingerprint,
        'parent_batch_id': batch.parent_batch_id,
        'screen_state': batch.screen_state,
        'screen_job_id': batch.screen_job_id,
        'screened_count': batch.screened_count,
        'screened_at': batch.screened_at,
        'cancelled_by': batch.cancelled_by,
        'cancelled_at': batch.cancelled_at,
        'cancel_reason': batch.cancel_reason,
        'hive_ids': [row.hive_id for row in _roster(db, batch.id)],
        'progress': data,
        'next_action': next_action(batch),
    }


def next_action(batch):
    return {
        'claimed': '逐箱补录完整读数，再交接接收',
        'received': '主管核对后封存批次',
        'sealed': '已封存，可按封存读数筛查' if batch.screen_state not in ['done'] else '封存读数已完成筛查',
        'cancelled': '批次已取消，箱清单已释放',
    }.get(batch.state, '查看批次记录')


def _claim_issues(db, hive_ids):
    issues = []
    seen = set()
    duplicate = set()
    for hive_id in hive_ids:
        if hive_id in seen:
            duplicate.add(hive_id)
        seen.add(hive_id)
    hives = {h.id: h for h in db.scalars(select(Hive).where(Hive.id.in_(set(hive_ids)))).all()}
    for hive_id in dict.fromkeys(hive_ids):
        hive = hives.get(hive_id)
        if not hive:
            issues.append({'hive_id': hive_id, 'hive_code': f'#{hive_id}', 'reason': '蜂箱不存在'})
            continue
        reasons = []
        if hive_id in duplicate:
            reasons.append('领批清单内蜂箱重复')
        active_batch = db.scalar(
            select(InspectionBatch)
            .join(InspectionBatchHive, InspectionBatchHive.batch_id == InspectionBatch.id)
            .where(
                InspectionBatchHive.hive_id == hive_id,
                InspectionBatch.state.in_(ACTIVE_BATCH_STATES),
            )
            .order_by(InspectionBatch.id)
        )
        if active_batch:
            reasons.append(f'已在在途批次 {active_batch.code} 领用')
        care = db.scalar(
            select(CareAction)
            .join(Visit, CareAction.visit_id == Visit.id)
            .where(Visit.hive_id == hive_id, CareAction.status.in_(ACTIVE_CARE_STATES))
            .order_by(CareAction.id.desc())
        )
        if care:
            reasons.append(f'存在未结束处置 CARE-{care.id}')
        if hive.care_state in ('caring', 'needs_requeen'):
            reasons.append('箱况仍处于处置/待换王，请先在处置簿闭环')
        if db.scalar(
            select(ApiaryMove.id).where(
                ApiaryMove.hive_id == hive_id,
                ApiaryMove.state.in_(['requested', 'approved']),
            )
        ):
            reasons.append('在途转场期间蜂箱档案冻结')
        if reasons:
            issues.append({'hive_id': hive_id, 'hive_code': hive.code, 'reason': '；'.join(dict.fromkeys(reasons))})
    return issues


def _reject_claim(issues):
    return HTTPException(409, {'message': '整批拒绝领用：箱清单存在重复领用或未结束处置', 'issues': issues})


def claim(db, body, user):
    hive_ids = list(body.hive_ids)
    fingerprint = _fingerprint({'code': body.code, 'hive_ids': sorted(set(hive_ids)), 'note': body.note})
    if body.idempotency_key:
        existing = db.scalar(select(InspectionBatch).where(InspectionBatch.claim_key == body.idempotency_key))
        if existing:
            if existing.claim_fingerprint != fingerprint:
                raise HTTPException(409, '该重试键已用于另一批领用，请刷新后重新领批')
            return batch_view(db, existing)
    existing = db.scalar(select(InspectionBatch).where(InspectionBatch.code == body.code))
    if existing:
        if existing.state != 'cancelled' and existing.claim_fingerprint == fingerprint:
            # 自然键幂等：同一批号与同一箱清单视为同一次领批，不重复锁定。
            if body.idempotency_key and not existing.claim_key:
                existing.claim_key = body.idempotency_key
                db.commit()
            return batch_view(db, existing)
        raise HTTPException(409, f'批次编号 {body.code} 已存在且清单不同或已取消，请更换编号')
    hives = {
        h.id: h
        for h in db.scalars(
            select(Hive).where(Hive.id.in_(set(hive_ids))).order_by(Hive.id).with_for_update()
        ).all()
    }
    missing_ids = [hive_id for hive_id in dict.fromkeys(hive_ids) if hive_id not in hives]
    if missing_ids:
        raise _reject_claim(
            [{'hive_id': hive_id, 'hive_code': f'#{hive_id}', 'reason': '蜂箱不存在'} for hive_id in missing_ids]
        )
    issues = _claim_issues(db, hive_ids)
    if issues:
        raise _reject_claim(issues)
    batch = InspectionBatch(
        code=body.code,
        state='claimed',
        note=body.note,
        claimed_by=user.email,
        claimed_at=_now(),
        claim_key=body.idempotency_key,
        claim_fingerprint=fingerprint,
        hive_count=len(hive_ids),
    )
    db.add(batch)
    try:
        db.flush()
        for seq, hive_id in enumerate(hive_ids):
            hive = hives[hive_id]
            db.add(
                InspectionBatchHive(
                    batch_id=batch.id,
                    hive_id=hive.id,
                    hive_code=hive.code,
                    site=hive.site,
                    seq=seq,
                    active_key=hive.id,
                )
            )
        audit(db, user, f'领用巡检批次 {batch.code}，锁定 {len(hive_ids)} 箱')
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.scalar(select(InspectionBatch).where(InspectionBatch.claim_key == body.idempotency_key))
            if body.idempotency_key
            else None
        )
        if existing and existing.claim_fingerprint == fingerprint:
            return batch_view(db, existing)
        # 并发领批时由 active_key 唯一约束兜底：整批退回并给出当前占用原因。
        issues = _claim_issues(db, hive_ids)
        if issues:
            raise _reject_claim(issues)
        raise HTTPException(409, '该批领用与另一请求冲突，请刷新后重试')
    return batch_view(db, batch)


def _release_roster(db, batch_id):
    db.execute(
        update(InspectionBatchHive)
        .where(InspectionBatchHive.batch_id == batch_id)
        .values(active_key=None)
    )


def _successor(db, sealed_batch, hive, user):
    """封存后迟到的补录：并入侵该箱当前领批中的下一批，否则新开下一批并锁定该箱。"""
    active = db.scalar(
        select(InspectionBatch)
        .join(InspectionBatchHive, InspectionBatchHive.batch_id == InspectionBatch.id)
        .where(
            InspectionBatchHive.hive_id == hive.id,
            InspectionBatch.state == 'claimed',
        )
        .order_by(InspectionBatch.id)
    )
    if active:
        return active
    received = db.scalar(
        select(InspectionBatch)
        .join(InspectionBatchHive, InspectionBatchHive.batch_id == InspectionBatch.id)
        .where(
            InspectionBatchHive.hive_id == hive.id,
            InspectionBatch.state == 'received',
        )
        .order_by(InspectionBatch.id)
    )
    if received:
        raise HTTPException(
            409,
            f'该箱已交接接收于批次 {received.code}，等待主管封存或取消后再补录，迟到读数不能插入已接收批次',
        )
    count = (
        db.scalar(
            select(func.count())
            .select_from(InspectionBatch)
            .where(InspectionBatch.parent_batch_id == sealed_batch.id)
        )
        or 0
    )
    for code in (f'{sealed_batch.code}-L{count + 1}', f'{sealed_batch.code}-L{hive.id}'):
        if db.scalar(select(InspectionBatch.id).where(InspectionBatch.code == code)):
            continue
        try:
            with db.begin_nested():
                batch = InspectionBatch(
                    code=code,
                    state='claimed',
                    note=f'{sealed_batch.code} 封存后迟到补录',
                    claimed_by=user.email,
                    claimed_at=_now(),
                    claim_fingerprint='',
                    parent_batch_id=sealed_batch.id,
                    hive_count=1,
                )
                db.add(batch)
                db.flush()
                db.add(
                    InspectionBatchHive(
                        batch_id=batch.id,
                        hive_id=hive.id,
                        hive_code=hive.code,
                        site=hive.site,
                        seq=0,
                        active_key=hive.id,
                    )
                )
                db.flush()
            return batch
        except IntegrityError:
            # 同一箱的并发迟到补录已开出下一批：取回它，不产生第二批。
            existing = db.scalar(
                select(InspectionBatch)
                .join(InspectionBatchHive, InspectionBatchHive.batch_id == InspectionBatch.id)
                .where(
                    InspectionBatchHive.hive_id == hive.id,
                    InspectionBatch.state == 'claimed',
                )
                .order_by(InspectionBatch.id)
            )
            if existing:
                return existing
    raise HTTPException(409, '迟到补录与并发批次冲突，请刷新后重试')


def record_reading(db, key, body, user):
    batch = _batch(db, key, True)
    roster_hive = db.scalar(
        select(InspectionBatchHive).where(
            InspectionBatchHive.batch_id == batch.id,
            InspectionBatchHive.hive_id == body.hive_id,
        )
    )
    if not roster_hive:
        raise HTTPException(409, '该蜂箱不在本批锁定的箱清单内')
    if batch.state == 'cancelled':
        raise HTTPException(409, f'批次 {batch.code} 已取消，请重新领批后再补录')
    if batch.state == 'received':
        raise HTTPException(409, '本批已交接接收，不能再补录；请等待主管封存后建立下一批')
    hive = db.scalar(select(Hive).where(Hive.id == body.hive_id).with_for_update())
    if not hive:
        raise HTTPException(404, '蜂箱不存在')
    if batch.state == 'sealed':
        target = _successor(db, batch, hive, user)
        result = _insert_reading(db, target, hive, body, user, late_from=batch)
        db.commit()
        result['batch'] = batch_view(db, target)
        result['message'] = f'{batch.code} 已封存，迟到补录已进入批次 {target.code}'
        return result
    result = _insert_reading(db, batch, hive, body, user)
    db.commit()
    result['batch'] = batch_view(db, batch)
    if result.get('reading', {}).get('state') == 'conflict':
        result['message'] = '同一箱已有完整读数，本次读数作为冲突证据留在原批，未覆盖原值'
    return result


def _insert_reading(db, batch, hive, body, user, late_from=None):
    if body.client_reading_id:
        existing = db.scalar(
            select(InspectionReading).where(InspectionReading.client_key == body.client_reading_id)
        )
        if existing:
            return {
                'reading': _reading_view(existing),
                'redirected': late_from is not None,
                'duplicate': True,
            }
    values = {field: getattr(body, field) for field in FIELDS}
    missing = [FIELD_LABELS[field] for field in FIELDS if values[field] is None]
    complete = not missing
    complete_rows = db.scalars(
        select(InspectionReading)
        .where(
            InspectionReading.batch_id == batch.id,
            InspectionReading.hive_id == hive.id,
            InspectionReading.state.in_(['complete', 'accepted']),
        )
        .with_for_update()
    ).all()
    target = complete_rows[0] if complete_rows else None
    if body.correct_reading_id:
        if not complete:
            raise HTTPException(409, '更正读数必须是完整读数，缺项请继续补录')
        correction = db.scalar(
            select(InspectionReading)
            .where(InspectionReading.id == body.correct_reading_id)
            .with_for_update()
        )
        if not correction or correction.batch_id != batch.id or correction.hive_id != hive.id:
            raise HTTPException(409, '更正目标须为本批同箱读数')
        if correction.state != 'complete' or batch.state != 'claimed':
            raise HTTPException(409, '仅可更正本批接收前的完整读数')
        correction.state = 'superseded'
        correction.conflict_note = f'已由 {user.email} 更正'
        target = None
    if target is not None:
        same = all(getattr(target, field) == values[field] for field in FIELDS)
        if same:
            return {
                'reading': _reading_view(target),
                'redirected': late_from is not None,
                'duplicate': True,
            }
        row = InspectionReading(
            batch_id=batch.id,
            hive_id=hive.id,
            hive_code=hive.code,
            **values,
            state='conflict',
            missing_fields=missing,
            note=body.note,
            conflict_note=(
                f'与本批 R-{target.id} 完整读数冲突，未覆盖原值'
                if complete
                else f'本箱已有完整读数 R-{target.id}，缺项补录不能替代，未覆盖原值'
            ),
            recorded_by=user.email,
            recorded_at=_now(),
            client_key=body.client_reading_id,
        )
        db.add(row)
        db.flush()
        audit(db, user, f'批次 {batch.code} / {hive.code} 读数冲突，保留原完整读数 R-{target.id}')
        result = {
            'reading': _reading_view(row),
            'accepted': False,
            'conflict_with': _reading_view(target),
            'redirected': late_from is not None,
        }
        if late_from is not None:
            result['late_from_batch_id'] = late_from.id
            result['late_from_batch_code'] = late_from.code
        return result
    row = InspectionReading(
        batch_id=batch.id,
        hive_id=hive.id,
        hive_code=hive.code,
        **values,
        state='complete' if complete else 'incomplete',
        missing_fields=missing,
        note=body.note,
        conflict_note='',
        recorded_by=user.email,
        recorded_at=_now(),
        client_key=body.client_reading_id,
    )
    db.add(row)
    db.flush()
    audit(
        db,
        user,
        f'批次 {batch.code} / {hive.code} 补录读数 R-{row.id}，'
        + ('完整' if complete else '缺项：' + '、'.join(missing)),
    )
    result = {
        'reading': _reading_view(row),
        'accepted': complete,
        'redirected': late_from is not None,
    }
    if late_from is not None:
        result['late_from_batch_id'] = late_from.id
        result['late_from_batch_code'] = late_from.code
    return result


def receive(db, key, body, user):
    batch = _batch(db, key, True)
    if batch.state == 'sealed':
        raise HTTPException(409, '批次已封存，不能重复接收')
    if batch.state == 'cancelled':
        raise HTTPException(409, '批次已取消，不能接收')
    if batch.state == 'received':
        if body.idempotency_key and batch.receive_key == body.idempotency_key:
            # 中断后重试同一次接收：返回已接收批次，不重复记账。
            return batch_view(db, batch)
        raise HTTPException(409, '本批已交接接收，等待主管封存')
    roster = _roster(db, batch.id)
    complete = _complete_by_hive(db, batch.id)
    readings = _readings(db, batch.id)
    missing = [h for h in roster if h.hive_id not in complete]
    incomplete = [row for row in readings if row.state == 'incomplete']
    conflicts = [row for row in readings if row.state == 'conflict']
    if missing:
        raise HTTPException(
            409,
            {
                'message': f'交接未通过：{len(missing)} 箱缺完整读数，缺项留在原批继续补录',
                'missing': [{'hive_id': h.hive_id, 'hive_code': h.hive_code, 'site': h.site} for h in missing],
                'incomplete': [_reading_view(row) for row in incomplete],
                'conflicts': [_reading_view(row) for row in conflicts],
            },
        )
    batch.state = 'received'
    batch.received_by = user.email
    batch.received_at = _now()
    batch.receive_key = body.idempotency_key
    batch.hive_count = len(roster)
    batch.received_count = len(complete)
    batch.missing_count = 0
    batch.conflict_count = len(conflicts)
    audit(
        db,
        user,
        f'交接接收巡检批次 {batch.code}，{len(complete)} 箱各一条完整读数，冲突 {len(conflicts)} 条留在原批',
    )
    db.commit()
    return batch_view(db, batch)


def _visit_for_reading(db, reading, batch, hive, superseded_by):
    if superseded_by is not None:
        return None
    code = f'V-B{batch.id}-{hive.code}'
    visit = db.scalar(select(Visit).where(Visit.code == code))
    if visit:
        return visit
    older = db.scalars(
        select(Visit)
        .join(InspectionReading, InspectionReading.visit_id == Visit.id)
        .join(InspectionBatch, InspectionBatch.id == InspectionReading.batch_id)
        .where(
            InspectionBatch.id < batch.id,
            InspectionBatch.state == 'sealed',
            InspectionReading.hive_id == hive.id,
            Visit.hive_id == hive.id,
            Visit.status.in_(['recorded', 'screening', 'screened', 'blocked']),
        )
        .with_for_update()
    ).all()
    for old in older:
        old.status = 'stale'
    visit = Visit(
        code=code,
        hive_id=hive.id,
        weight_kg=reading.weight_kg,
        temperature=reading.temperature,
        activity=reading.activity,
        feed_left=reading.feed_left,
        queen_seen=reading.queen_seen,
        colony_frames=reading.colony_frames,
        status='recorded',
        recorded_at=_now(),
    )
    db.add(visit)
    db.flush()
    reading.visit_id = visit.id
    hive.queen_present = reading.queen_seen
    hive.colony_frames = reading.colony_frames
    if not reading.queen_seen:
        hive.care_state = 'needs_care'
    elif hive.care_state not in ('needs_requeen', 'winter_ready', 'spring_ready'):
        hive.care_state = 'observe'
    return visit


def seal(db, key, body, user):
    batch = _batch(db, key, True)
    if batch.state == 'sealed':
        if body.idempotency_key and batch.seal_key == body.idempotency_key:
            return batch_view(db, batch)
        if batch.sealed_by == user.email and batch.seal_reason == body.reason:
            # 中断后重试同一封存动作：返回已有封存，不产生第二份快照。
            return batch_view(db, batch)
        raise HTTPException(409, '批次已封存，不能重复封存')
    if batch.state == 'cancelled':
        raise HTTPException(409, '批次已取消，不能封存')
    if batch.state != 'received':
        raise HTTPException(409, '请先完成交接接收，再由主管封存')
    roster = _roster(db, batch.id)
    complete = _complete_by_hive(db, batch.id)
    missing = [h for h in roster if h.hive_id not in complete]
    if missing:
        raise HTTPException(
            409,
            {
                'message': '封存前复核发现缺少完整读数，请退回补录',
                'missing': [{'hive_id': h.hive_id, 'hive_code': h.hive_code} for h in missing],
            },
        )
    hives = {
        h.id: h
        for h in db.scalars(
            select(Hive)
            .where(Hive.id.in_([item.hive_id for item in roster]))
            .order_by(Hive.id)
            .with_for_update()
        ).all()
    }
    active_care = db.scalars(
        select(CareAction)
        .join(Visit, CareAction.visit_id == Visit.id)
        .where(
            Visit.hive_id.in_([item.hive_id for item in roster]),
            CareAction.status.in_(ACTIVE_CARE_STATES),
        )
    ).all()
    if active_care:
        raise HTTPException(
            409,
            {
                'message': '封存前发现蜂箱有未结束处置，请先在处置簿闭环',
                'care': [
                    {'care_id': item.id, 'hive_id': db.get(Visit, item.visit_id).hive_id, 'status': item.status}
                    for item in active_care
                ],
            },
        )
    readings = _readings(db, batch.id)
    conflicts = [row for row in readings if row.state == 'conflict']
    sealed_at = _now()
    snapshot_rows = []
    for roster_hive in roster:
        hive = hives[roster_hive.hive_id]
        reading = complete[hive.id]
        newer = db.scalar(
            select(func.max(InspectionBatch.id))
            .join(InspectionBatchHive, InspectionBatchHive.batch_id == InspectionBatch.id)
            .where(
                InspectionBatchHive.hive_id == hive.id,
                InspectionBatch.state == 'sealed',
                InspectionBatch.id > batch.id,
            )
        )
        visit = _visit_for_reading(db, reading, batch, hive, newer)
        snapshot_rows.append(
            {
                'hive_id': hive.id,
                'hive_code': roster_hive.hive_code,
                'site': roster_hive.site,
                'reading_id': reading.id,
                'weight_kg': reading.weight_kg,
                'temperature': reading.temperature,
                'activity': reading.activity,
                'feed_left': reading.feed_left,
                'queen_seen': reading.queen_seen,
                'colony_frames': reading.colony_frames,
                'recorded_by': reading.recorded_by,
                'recorded_at': reading.recorded_at.isoformat() if reading.recorded_at else None,
                'visit_id': visit.id if visit else None,
                'superseded_by_batch_id': newer,
            }
        )
    snapshot = {
        'batch_id': batch.id,
        'code': batch.code,
        'claimed_by': batch.claimed_by,
        'claimed_at': batch.claimed_at.isoformat() if batch.claimed_at else None,
        'received_by': batch.received_by,
        'received_at': batch.received_at.isoformat() if batch.received_at else None,
        'sealed_by': user.email,
        'sealed_at': sealed_at.isoformat(),
        'reason': body.reason,
        'hive_count': len(roster),
        'complete_count': len(complete),
        'conflict_count': len(conflicts),
        'hives': snapshot_rows,
    }
    fingerprint = _fingerprint(snapshot)
    batch.state = 'sealed'
    batch.sealed_by = user.email
    batch.sealed_at = sealed_at
    batch.seal_reason = body.reason
    batch.seal_key = body.idempotency_key
    batch.seal_snapshot = {**snapshot, 'fingerprint': fingerprint}
    batch.seal_fingerprint = fingerprint
    batch.hive_count = len(roster)
    batch.received_count = len(complete)
    batch.missing_count = 0
    batch.conflict_count = len(conflicts)
    batch.screen_state = 'idle'
    _release_roster(db, batch.id)
    audit(db, user, f'主管封存巡检批次 {batch.code}，{len(complete)} 箱封存读数，依据：{body.reason}')
    db.commit()
    return batch_view(db, batch)


def cancel(db, key, body, user):
    batch = _batch(db, key, True)
    if batch.state not in ACTIVE_BATCH_STATES:
        raise HTTPException(409, '仅未封存且未取消的批次可以取消')
    batch.state = 'cancelled'
    batch.cancelled_by = user.email
    batch.cancelled_at = _now()
    batch.cancel_reason = body.reason.strip()
    _release_roster(db, batch.id)
    audit(db, user, f'取消巡检批次 {batch.code}，释放箱清单，依据：{batch.cancel_reason}')
    db.commit()
    return batch_view(db, batch)


def screen(db, key, user, queue):
    batch = _batch(db, key, True)
    if batch.state != 'sealed':
        raise HTTPException(409, '仅已封存批次可以用封存读数筛查')
    if batch.screen_state == 'done':
        raise HTTPException(409, '该封存批次已完成筛查，封存读数未变，不重复覆盖分值')
    if (
        batch.screen_state in ('queued', 'running')
        and batch.screen_job_id
        and batch.screen_queued_at
        and _now() - batch.screen_queued_at < RESCREEN_AFTER
    ):
        return {
            'job_id': batch.screen_job_id,
            'state': batch.screen_state,
            'batch_id': batch.id,
            'reused': True,
        }
    snapshot = batch.seal_snapshot or {}
    reading_ids = [row['reading_id'] for row in snapshot.get('hives', []) if row.get('reading_id')]
    if not reading_ids:
        raise HTTPException(409, '封存快照中没有可筛查读数')
    jobid = uuid.uuid4().hex
    batch.screen_state = 'queued'
    batch.screen_job_id = jobid
    batch.screen_queued_at = _now()
    audit(db, user, f'按封存读数发起批次 {batch.code} 筛查，{len(reading_ids)} 箱')
    db.commit()
    queue.set(
        f'apiary:batch-screen:{jobid}',
        json.dumps({'status': 'queued', 'batch_id': batch.id, 'reading_ids': reading_ids}),
        ex=86400,
    )
    queue.rpush(
        'apiary:batch-screen',
        json.dumps({'job_id': jobid, 'batch_id': batch.id, 'reading_ids': reading_ids}),
    )
    return {
        'job_id': jobid,
        'state': 'queued',
        'batch_id': batch.id,
        'count': len(reading_ids),
        'reused': False,
    }


def current_sealed_batch(db, hive_id):
    return db.scalar(
        select(func.max(InspectionBatch.id))
        .join(InspectionBatchHive, InspectionBatchHive.batch_id == InspectionBatch.id)
        .where(InspectionBatchHive.hive_id == hive_id, InspectionBatch.state == 'sealed')
    )


def apply_reading_screen(db, reading_id):
    """把封存读数送入无监督模型；只有仍是该箱最新封存批时才更新箱况与巡检状态。"""
    from .screen_model import screen as run_screen

    reading = db.scalar(select(InspectionReading).where(InspectionReading.id == reading_id).with_for_update())
    if not reading:
        return None
    batch = _batch(db, reading.batch_id)
    if batch.state != 'sealed':
        return None
    hive = db.scalar(select(Hive).where(Hive.id == reading.hive_id).with_for_update())
    score, flag, margin, evidence = run_screen(reading)
    reading.anomaly_score = score
    reading.anomaly_flag = flag
    reading.decision_margin = margin
    reading.model_evidence = evidence
    is_current = current_sealed_batch(db, hive.id) == batch.id
    visit = db.get(Visit, reading.visit_id) if reading.visit_id else None
    if visit:
        visit.anomaly_score = score
        visit.anomaly_flag = flag
        visit.decision_margin = margin
        visit.model_evidence = evidence
        latest_id = db.scalar(select(func.max(Visit.id)).where(Visit.hive_id == hive.id))
        if is_current and latest_id == visit.id:
            if visit.status in ('recorded', 'screening', 'screened'):
                visit.status = 'screened'
            if hive.care_state not in ('caring', 'needs_requeen', 'winter_ready'):
                hive.care_state = 'needs_care' if flag or not visit.queen_seen else 'observe'
        elif not is_current and visit.status in ('recorded', 'screening', 'screened', 'blocked'):
            visit.status = 'stale'
    return {
        'reading_id': reading.id,
        'hive_id': reading.hive_id,
        'hive_code': reading.hive_code,
        'score': score,
        'flag': flag,
        'current': is_current,
        'visit_id': reading.visit_id,
    }


def finish_screen(db, batch_id, points, error=None):
    batch = _batch(db, batch_id, True)
    if error:
        batch.screen_state = 'failed'
        return batch
    batch.screen_state = 'done'
    batch.screened_count = len(points or [])
    batch.screened_at = _now()
    return batch
