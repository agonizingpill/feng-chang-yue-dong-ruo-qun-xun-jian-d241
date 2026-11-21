import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from .database import session
from .auth import current, editor, admin
from .batch_models import InspectionBatch
from .batch_schemas import ClaimInput, ReadingInput, ReceiveInput, SealInput, CancelInput
from . import batch_service
from .app_queue import queue

router = APIRouter()


@router.get('/inspection-batches')
def batches(user=Depends(current), db=Depends(session)):
    rows = db.scalars(select(InspectionBatch).order_by(InspectionBatch.id.desc())).all()
    return [batch_service.batch_summary(db, row) for row in rows]


@router.get('/inspection-batches/{key}')
def batch(key: int, user=Depends(current), db=Depends(session)):
    return batch_service.batch_view(db, batch_service._batch(db, key))


@router.post('/inspection-batches')
def claim(body: ClaimInput, user=Depends(editor), db=Depends(session)):
    return batch_service.claim(db, body, user)


@router.post('/inspection-batches/{key}/readings')
def reading(key: int, body: ReadingInput, user=Depends(editor), db=Depends(session)):
    return batch_service.record_reading(db, key, body, user)


@router.post('/inspection-batches/{key}/receive')
def receive(key: int, body: ReceiveInput | None = None, user=Depends(admin), db=Depends(session)):
    return batch_service.receive(db, key, body or ReceiveInput(), user)


@router.post('/inspection-batches/{key}/seal')
def seal(key: int, body: SealInput, user=Depends(admin), db=Depends(session)):
    return batch_service.seal(db, key, body, user)


@router.post('/inspection-batches/{key}/cancel')
def cancel(key: int, body: CancelInput, user=Depends(editor), db=Depends(session)):
    return batch_service.cancel(db, key, body, user)


@router.post('/inspection-batches/{key}/screen')
def screen(key: int, user=Depends(editor), db=Depends(session)):
    return batch_service.screen(db, key, user, queue)


@router.get('/inspection-batches/{key}/screen/{jobid}')
def screen_result(key: int, jobid: str, user=Depends(current), db=Depends(session)):
    result = queue.get('apiary:batch-screen:' + jobid)
    if not result:
        raise HTTPException(404, '批次筛查结果已过期，请重新筛查')
    return json.loads(result)
