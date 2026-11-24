"""Authenticated source, history and handling actions for operational cases."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import casework_service as service
from .operations_evidence import actor_field
from .security import current_user
from .database import SessionLocal
from .models import DelayCase
from . import grade_explanation

router = APIRouter(prefix='/api/operational-cases', tags=['业务处置'])


class HandlingAction(BaseModel):
    action: Literal['submit', 'approve', 'return']
    revision: int = Field(ge=0)
    note: str = Field(min_length=4, max_length=500)
    outcome: str = Field(default='', max_length=40)
    reference: str = Field(default='', max_length=120)


@router.get('')
def catalog(user=Depends(current_user)):
    return {
        'role': actor_field(user, 'role'),
        'workflows': {code: {
            'title': workflow['title'], 'reference_label': workflow['reference_label'],
            'outcomes': {value: label for value, (label, _) in workflow['outcomes'].items()},
        } for code, workflow in service.WORKFLOWS.items()},
    }


@router.get('/{workflow}/sources')
def sources(workflow: str, user=Depends(current_user)):
    return service.source_rows(service.workflow_for(workflow))


@router.get('/{workflow}/history')
def history(workflow: str, key: str = Query(min_length=1, max_length=100), user=Depends(current_user)):
    return service.case_view(workflow, key)


@router.post('/{workflow}/actions', status_code=201)
def act(workflow: str, action: HandlingAction, key: str = Query(min_length=1, max_length=100), user=Depends(current_user)):
    return service.change(workflow, key, action, user)


def _delay_case_by_key(key: str):
    db = SessionLocal()
    try:
        case = db.execute(select(DelayCase).where(DelayCase.case_no == key)).scalar_one_or_none()
        if not case:
            raise HTTPException(404, '找不到对应的延误案件')
        return db, case
    except Exception:
        db.close()
        raise


@router.get('/{workflow}/grade-explanation')
def grade_explanation_view(workflow: str, key: str = Query(min_length=1, max_length=100), user=Depends(current_user)):
    service.workflow_for(workflow)
    db, case = _delay_case_by_key(key)
    try:
        return {
            'role': actor_field(user, 'role'),
            'case_no': case.case_no,
            'traceability': grade_explanation.traceability(db, case),
            'explanations': grade_explanation.list_for_case(db, case.id),
        }
    finally:
        db.close()


@router.post('/{workflow}/grade-explanation', status_code=201)
def issue_grade_explanation(workflow: str, key: str = Query(min_length=1, max_length=100), user=Depends(current_user)):
    service.workflow_for(workflow)
    if actor_field(user, 'role') != 'supervisor':
        raise HTTPException(403, '只有主管可以签发分级说明')
    db, case = _delay_case_by_key(key)
    try:
        record, reused = grade_explanation.issue_for_case(db, case, user)
        db.commit()
        return {
            'role': actor_field(user, 'role'),
            'case_no': case.case_no,
            'explanation': grade_explanation.serialize(record),
            'reused': reused,
            'message': '已存在签发原件，按原件返回' if reused else '分级说明已签发',
        }
    finally:
        db.close()
