import json, os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .database import redis_client
from .models import AuditLog, AnalysisJob, ContainerCheck, DelayCase, DispatchAction, GateEvent, GradeExplanation, User, VesselCall
from .schemas import ContainerIn, CustomsUpdate, DelayCaseIn, DispatchIn, GateIn, GradeExplanationIn, LoginIn, VesselIn
from .security import current_user, get_db, hash_password, issue_token, require_roles
from .services import build_features, domain_precheck
from . import grade_explanation

router = APIRouter(prefix="/api")

def log(db, user, action, entity, entity_id=None, detail=""):
    db.add(AuditLog(actor=user.username, role=user.role, action=action, entity=entity, entity_id=entity_id, detail=detail))

def vessel_dict(v: VesselCall, db):
    features, issues = domain_precheck(db, v)
    return {"id": v.id, "call_no": v.call_no, "vessel_name": v.vessel_name, "terminal": v.terminal, "berth": v.berth, "eta": v.eta.isoformat(), "etd": v.etd.isoformat(), "window_status": v.window_status, "state": v.state, "notes": v.notes, "container_count": len(v.containers), "open_customs": features["customs_open_count"], "gate_events": features["gate_event_count"], "issues": issues, "features": features}

def case_dict(c: DelayCase, db):
    jobs = db.execute(select(AnalysisJob).where(AnalysisJob.case_id == c.id).order_by(AnalysisJob.id.desc())).scalars().all()
    actions = [{"id": a.id, "action_type": a.action_type, "assignee": a.assignee, "due_at": a.due_at.isoformat(), "status": a.status, "instruction": a.instruction, "analysis_job_id": a.analysis_job_id, "graded_level_snapshot": a.graded_level_snapshot} for a in c.actions]
    explanations = grade_explanation.list_for_case(db, c.id)
    return {"id": c.id, "case_no": c.case_no, "vessel_id": c.vessel_id, "vessel": c.vessel.call_no if c.vessel else "", "vessel_name": c.vessel.vessel_name if c.vessel else "", "requested_level": c.requested_level, "final_level": c.final_level, "status": c.status, "reason": c.reason, "feature_snapshot": c.feature_snapshot, "model_output": c.model_output, "exception_reason": c.exception_reason, "jobs": [{"id": j.id, "status": j.status, "result": j.result, "error": j.error, "finished_at": j.finished_at.isoformat() if j.finished_at else None} for j in jobs], "actions": actions, "grade_explanations": explanations, "traceability": grade_explanation.traceability(db, c)}

@router.post("/auth/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if not user or user.password_hash != hash_password(payload.password):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    return {"access_token": issue_token(user), "token_type": "bearer", "user": {"username": user.username, "display_name": user.display_name, "role": user.role}}

@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"username": user.username, "display_name": user.display_name, "role": user.role}

@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    vessels = db.execute(select(VesselCall).order_by(VesselCall.eta)).scalars().all()
    cases = db.execute(select(DelayCase).order_by(DelayCase.id.desc())).scalars().all()
    return {"stats": {"vessels": len(vessels), "containers": db.scalar(select(func.count(ContainerCheck.id))), "open_cases": sum(1 for c in cases if c.status not in {"closed", "rejected"}), "dispatches": db.scalar(select(func.count(DispatchAction.id)))}, "vessels": [vessel_dict(v, db) for v in vessels], "cases": [case_dict(c, db) for c in cases]}

@router.get("/vessels")
def list_vessels(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [vessel_dict(v, db) for v in db.execute(select(VesselCall).order_by(VesselCall.eta)).scalars().all()]

@router.post("/vessels")
def create_vessel(payload: VesselIn, db: Session = Depends(get_db), user: User = Depends(require_roles("operator", "supervisor"))):
    if payload.etd <= payload.eta:
        raise HTTPException(status_code=422, detail="离港时间必须晚于靠泊时间")
    if db.execute(select(VesselCall).where(VesselCall.call_no == payload.call_no)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="船次号已存在")
    v = VesselCall(**payload.model_dump())
    db.add(v); db.flush(); log(db, user, "create_vessel", "vessel_call", v.id, payload.call_no); db.commit()
    return vessel_dict(v, db)

@router.post("/containers")
def create_container(payload: ContainerIn, db: Session = Depends(get_db), user: User = Depends(require_roles("operator", "supervisor"))):
    if not db.get(VesselCall, payload.vessel_id): raise HTTPException(404, "船次不存在")
    if db.execute(select(ContainerCheck).where(ContainerCheck.container_no == payload.container_no)).scalar_one_or_none(): raise HTTPException(409, "箱号已存在")
    c = ContainerCheck(**payload.model_dump()); db.add(c); db.flush(); log(db, user, "create_container", "container_check", c.id, payload.container_no); db.commit()
    return {"id": c.id, "container_no": c.container_no, "vessel_id": c.vessel_id}

@router.post("/gates")
def create_gate(payload: GateIn, db: Session = Depends(get_db), user: User = Depends(require_roles("operator", "supervisor"))):
    c = db.get(ContainerCheck, payload.container_id)
    if not c: raise HTTPException(404, "箱单不存在")
    g = GateEvent(**payload.model_dump()); db.add(g); db.flush(); log(db, user, "create_gate_event", "gate_event", g.id, payload.event_ref); db.commit()
    return {"id": g.id, "status": g.status, "container_no": c.container_no}

@router.post("/gates/{gate_id}/reverse")
def reverse_gate(gate_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("supervisor"))):
    g = db.get(GateEvent, gate_id)
    if not g: raise HTTPException(404, "闸口记录不存在")
    if g.status == "reversed": raise HTTPException(409, "记录已冲正")
    g.status = "reversed"; g.note = f"{g.note} | 主管 {user.username} 于 {datetime.now(timezone.utc).isoformat()} 冲正"
    log(db, user, "reverse_gate_event", "gate_event", g.id, g.event_ref); db.commit()
    return {"id": g.id, "status": g.status}

@router.post("/containers/{container_id}/customs")
def update_customs(container_id: int, payload: CustomsUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("operator", "supervisor"))):
    if payload.customs_status not in {"pending", "in_progress", "finished"}: raise HTTPException(422, "查验状态不合法")
    c = db.get(ContainerCheck, container_id)
    if not c: raise HTTPException(404, "箱单不存在")
    c.customs_status = payload.customs_status; c.check_state = "verified" if payload.customs_status == "finished" else "pending"
    log(db, user, "update_customs", "container_check", c.id, payload.customs_status); db.commit()
    return {"id": c.id, "container_no": c.container_no, "customs_status": c.customs_status}

@router.get("/containers")
def list_containers(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(select(ContainerCheck).order_by(ContainerCheck.id)).scalars().all()
    return [{"id": c.id, "container_no": c.container_no, "vessel_id": c.vessel_id, "vessel": c.vessel.call_no, "iso_type": c.iso_type, "cargo_class": c.cargo_class, "weight_t": c.weight_t, "customs_status": c.customs_status, "seal_status": c.seal_status, "gates": [{"id": g.id, "event_ref": g.event_ref, "gate_code": g.gate_code, "event_type": g.event_type, "dwell_min": g.dwell_min, "status": g.status} for g in c.gates]} for c in rows]

@router.get("/cases")
def list_cases(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [case_dict(c, db) for c in db.execute(select(DelayCase).order_by(DelayCase.id.desc())).scalars().all()]

@router.post("/cases")
def create_case(payload: DelayCaseIn, db: Session = Depends(get_db), user: User = Depends(require_roles("operator", "supervisor"))):
    vessel = db.get(VesselCall, payload.vessel_id)
    if not vessel: raise HTTPException(404, "船次不存在")
    if db.execute(select(DelayCase).where(DelayCase.case_no == payload.case_no)).scalar_one_or_none(): raise HTTPException(409, "案件号已存在")
    c = DelayCase(vessel_id=vessel.id, case_no=payload.case_no, reason=payload.reason, status="draft")
    db.add(c); db.flush(); log(db, user, "create_delay_case", "delay_case", c.id, payload.case_no); db.commit()
    return case_dict(c, db)

@router.post("/cases/{case_id}/classify")
def classify(case_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("operator", "supervisor"))):
    case = db.get(DelayCase, case_id)
    if not case: raise HTTPException(404, "延误案件不存在")
    features, issues = domain_precheck(db, case.vessel)
    case.feature_snapshot = features
    if issues:
        case.status = "blocked"; case.exception_reason = "；".join(issues); case.updated_at = datetime.now(timezone.utc)
        log(db, user, "triage_blocked", "delay_case", case.id, case.exception_reason); db.commit()
        raise HTTPException(status_code=409, detail={"code": "DOMAIN_PRECHECK", "message": case.exception_reason, "case": case_dict(case, db)})
    case.status = "queued"; case.exception_reason = None
    job = AnalysisJob(case_id=case.id, status="queued", input_summary=features)
    db.add(job); db.flush(); log(db, user, "triage_queued", "analysis_job", job.id, json.dumps(features, ensure_ascii=False)); db.commit()
    redis_client.rpush("container_delay_triage_jobs", str(job.id))
    return {"case": case_dict(case, db), "job_id": job.id, "message": "已排入交叉特征分级队列"}

@router.post("/cases/{case_id}/actions")
def create_action(case_id: int, payload: DispatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("supervisor"))):
    case = db.get(DelayCase, case_id)
    if not case: raise HTTPException(404, "延误案件不存在")
    if case.status not in {"classified", "dispatched"} or not case.final_level: raise HTTPException(409, "案件尚未完成分级，不能生成调度动作")
    # 派工与分级结果同时落库：冻结派工当时采用的那次推理与等级
    adopted_job = db.execute(select(AnalysisJob).where(AnalysisJob.case_id == case.id, AnalysisJob.status == "succeeded").order_by(AnalysisJob.id.desc())).scalars().first()
    a = DispatchAction(case_id=case.id, **payload.model_dump(), analysis_job_id=adopted_job.id if adopted_job else None, graded_level_snapshot=case.final_level)
    case.status = "dispatched"; db.add(a); db.flush(); log(db, user, "create_dispatch_action", "dispatch_action", a.id, f"{payload.action_type}｜采用推理 job={a.analysis_job_id} 等级={a.graded_level_snapshot}"); db.commit()
    return {"id": a.id, "case_id": case.id, "status": a.status, "analysis_job_id": a.analysis_job_id, "graded_level_snapshot": a.graded_level_snapshot}

@router.get("/cases/{case_id}/grade-explanations")
def get_grade_explanations(case_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    case = db.get(DelayCase, case_id)
    if not case: raise HTTPException(404, "延误案件不存在")
    return {"traceability": grade_explanation.traceability(db, case), "explanations": grade_explanation.list_for_case(db, case.id)}

@router.post("/cases/{case_id}/grade-explanations", status_code=201)
def issue_grade_explanation(case_id: int, payload: GradeExplanationIn, db: Session = Depends(get_db), user: User = Depends(require_roles("supervisor"))):
    case = db.get(DelayCase, case_id)
    if not case: raise HTTPException(404, "延误案件不存在")
    record, reused = grade_explanation.issue_for_case(db, case, user, payload.dispatch_action_id)
    log(db, user, "issue_grade_explanation" if not reused else "reuse_grade_explanation", "grade_explanation", record.id, f"case={case.case_no} level={record.explained_level} job={record.analysis_job_id}")
    db.commit()
    return {"explanation": grade_explanation.serialize(record), "reused": reused, "message": "已存在签发原件，按原件返回" if reused else "分级说明已签发"}

@router.get("/dispatch-actions/{action_id}/grade-explanation")
def action_grade_explanation(action_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    action = db.get(DispatchAction, action_id)
    if not action: raise HTTPException(404, "调度动作不存在")
    record = db.execute(select(GradeExplanation).where(GradeExplanation.dispatch_action_id == action.id)).scalar_one_or_none()
    if not record:
        return {"explanation": None, "traceability": grade_explanation.traceability(db, action.case)}
    return {"explanation": grade_explanation.serialize(record), "traceability": grade_explanation.traceability(db, action.case)}

@router.post("/actions/{action_id}/complete")
def complete_action(action_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("operator", "supervisor"))):
    a = db.get(DispatchAction, action_id)
    if not a: raise HTTPException(404, "调度动作不存在")
    a.status = "completed"; a.completed_at = datetime.now(timezone.utc); log(db, user, "complete_dispatch_action", "dispatch_action", a.id, a.action_type); db.commit()
    return {"id": a.id, "status": a.status}

@router.get("/audit")
def audit(db: Session = Depends(get_db), user: User = Depends(require_roles("supervisor"))):
    return [{"id": x.id, "actor": x.actor, "role": x.role, "action": x.action, "entity": x.entity, "detail": x.detail, "created_at": x.created_at.isoformat()} for x in db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(80)).scalars().all()]
