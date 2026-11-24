from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from src.database import Base, SessionLocal, engine
from src.models import User, VesselCall, ContainerCheck, GateEvent, DelayCase, DispatchAction
from src.security import hash_password


def dt(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc)

def seed():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        users = [("operator", "林岚", "operator123", "operator"), ("supervisor", "顾航", "supervisor123", "supervisor"), ("viewer", "周宁", "viewer123", "viewer")]
        for username, display, password, role in users:
            if not db.execute(select(User).where(User.username == username)).scalar_one_or_none():
                db.add(User(username=username, display_name=display, password_hash=hash_password(password), role=role))
        calls = [
            ("CALL-HAI-20261121", "海岚星", "海陵港CCT", "C12", dt(21, 6), dt(21, 14), "准班窗口，优先处理冷藏箱"),
            ("CALL-TRI-20261121", "天际三号", "海陵港CCT", "C08", dt(21, 8), dt(21, 13), "查验箱集中在上午窗口"),
            ("CALL-PEARL-20261121", "珠江门", "海陵港CCT", "C15", dt(21, 9), dt(21, 16), "危险品箱需单独排队"),
            ("CALL-NORTH-20261121", "北辰航运", "海陵港CCT", "C03", dt(21, 11), dt(21, 19), "晚靠泊，观察潮汐"),
        ]
        for call_no, name, terminal, berth, eta, etd, notes in calls:
            if not db.execute(select(VesselCall).where(VesselCall.call_no == call_no)).scalar_one_or_none():
                db.add(VesselCall(call_no=call_no, vessel_name=name, terminal=terminal, berth=berth, eta=eta, etd=etd, window_status="planned", state="open", notes=notes))
        db.flush()
        vessel_by_no = {v.call_no: v for v in db.execute(select(VesselCall)).scalars().all()}
        containers = [
            ("MSCU100001", "CALL-HAI-20261121", "22G1", "dry", 18.4, "finished"),
            ("MSCU100002", "CALL-HAI-20261121", "45R1", "reefer", 21.2, "finished"),
            ("MSCU100003", "CALL-HAI-20261121", "22G1", "dry", 16.1, "finished"),
            ("MSCU200001", "CALL-TRI-20261121", "45G1", "dry", 19.7, "in_progress"),
            ("MSCU200002", "CALL-TRI-20261121", "22G1", "dry", 17.9, "finished"),
            ("MSCU200003", "CALL-TRI-20261121", "45R1", "reefer", 23.1, "finished"),
            ("MSCU300001", "CALL-PEARL-20261121", "22G1", "hazmat", 20.2, "finished"),
            ("MSCU300002", "CALL-PEARL-20261121", "45R1", "reefer", 22.7, "finished"),
            ("MSCU300003", "CALL-PEARL-20261121", "22G1", "dry", 18.8, "finished"),
            ("MSCU400001", "CALL-NORTH-20261121", "22G1", "dry", 15.2, "finished"),
            ("MSCU400002", "CALL-NORTH-20261121", "45R1", "reefer", 22.2, "finished"),
        ]
        for no, call_no, iso, cargo, weight, customs in containers:
            if not db.execute(select(ContainerCheck).where(ContainerCheck.container_no == no)).scalar_one_or_none():
                db.add(ContainerCheck(vessel_id=vessel_by_no[call_no].id, container_no=no, iso_type=iso, cargo_class=cargo, weight_t=weight, customs_status=customs, seal_status="intact", check_state="verified" if customs == "finished" else "pending"))
        db.flush()
        c_by_no = {c.container_no: c for c in db.execute(select(ContainerCheck)).scalars().all()}
        gates = [
            ("MSCU100001", "GATE-H-001", "G12", "in", 8, dt(21, 6, 22)), ("MSCU100001", "GATE-H-002", "G12", "out", 12, dt(21, 7, 10)),
            ("MSCU100002", "GATE-H-003", "G14", "in", 18, dt(21, 6, 35)), ("MSCU100003", "GATE-H-004", "G12", "in", 10, dt(21, 6, 42)),
            ("MSCU200001", "GATE-T-001", "G08", "in", 31, dt(21, 8, 25)), ("MSCU200002", "GATE-T-002", "G08", "in", 28, dt(21, 8, 32)), ("MSCU200003", "GATE-T-003", "G09", "in", 24, dt(21, 8, 45)),
            ("MSCU300001", "GATE-P-001", "G15", "in", 42, dt(21, 9, 25)), ("MSCU300002", "GATE-P-002", "G15", "in", 38, dt(21, 9, 28)), ("MSCU300003", "GATE-P-003", "G15", "in", 35, dt(21, 9, 36)),
            ("MSCU400001", "GATE-N-001", "G03", "in", 16, dt(21, 11, 20)), ("MSCU400002", "GATE-ERR-77", "G03", "in", 23, dt(21, 11, 25)),
        ]
        for no, ref, gate, typ, dwell, when in gates:
            if not db.execute(select(GateEvent).where(GateEvent.event_ref == ref)).scalar_one_or_none():
                db.add(GateEvent(container_id=c_by_no[no].id, event_ref=ref, gate_code=gate, event_type=typ, event_time=when, dwell_min=dwell, status="active", note="闸口采集"))
        db.flush()
        if not db.execute(select(GateEvent).where(GateEvent.event_ref == "GATE-ERR-77-R2")).scalar_one_or_none():
            db.add(GateEvent(container_id=c_by_no["MSCU400002"].id, event_ref="GATE-ERR-77-R2", gate_code="G03", event_type="in", event_time=dt(21, 11, 25), dwell_min=23, status="active", note="重复上报，待主管冲正"))
        cases = [("CASE-HAI-001", "CALL-HAI-20261121", "C12卸船队列出现短时拥堵，优先保护冷藏箱"), ("CASE-TRI-002", "CALL-TRI-20261121", "查验箱未回执，不能直接按普通延误放行"), ("CASE-NORTH-004", "CALL-NORTH-20261121", "同箱闸口重复记录，需冲正后重新分级")]
        for case_no, call_no, reason in cases:
            if not db.execute(select(DelayCase).where(DelayCase.case_no == case_no)).scalar_one_or_none():
                db.add(DelayCase(vessel_id=vessel_by_no[call_no].id, case_no=case_no, requested_level="pending", status="draft", reason=reason))
        db.flush()
        if not db.execute(select(DispatchAction).where(DispatchAction.action_type == "冷藏箱优先卸船")).scalar_one_or_none():
            case = db.execute(select(DelayCase).where(DelayCase.case_no == "CASE-HAI-001")).scalar_one()
            case.status = "dispatched"; case.final_level = "major"
            case.model_output = {"label": "major", "confidence": 0.84, "seed": 42, "note": "seed演示结果"}
            db.add(DispatchAction(case_id=case.id, action_type="冷藏箱优先卸船", assignee="C12夜班桥吊组", due_at=dt(21, 8, 30), status="queued", instruction="将MSCU100002置于前两吊，完成后回报调度台"))
        if not db.execute(select(DispatchAction).where(DispatchAction.action_type == "查验单证补录")).scalar_one_or_none():
            case = db.execute(select(DelayCase).where(DelayCase.case_no == "CASE-TRI-002")).scalar_one()
            db.add(DispatchAction(case_id=case.id, action_type="查验单证补录", assignee="海关联络岗", due_at=dt(21, 10), status="queued", instruction="等查验结束后补传查验回执"))
        db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    seed()
