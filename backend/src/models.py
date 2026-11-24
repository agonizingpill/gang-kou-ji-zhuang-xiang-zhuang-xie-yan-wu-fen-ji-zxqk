from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def now_utc():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(20))

class VesselCall(Base):
    __tablename__ = "vessel_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    call_no: Mapped[str] = mapped_column(String(40), unique=True)
    vessel_name: Mapped[str] = mapped_column(String(100))
    terminal: Mapped[str] = mapped_column(String(60))
    berth: Mapped[str] = mapped_column(String(20))
    eta: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    etd: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_status: Mapped[str] = mapped_column(String(20), default="planned")
    state: Mapped[str] = mapped_column(String(20), default="open")
    notes: Mapped[str] = mapped_column(Text, default="")
    containers: Mapped[list["ContainerCheck"]] = relationship(back_populates="vessel", cascade="all, delete-orphan")
    cases: Mapped[list["DelayCase"]] = relationship(back_populates="vessel", cascade="all, delete-orphan")

class ContainerCheck(Base):
    __tablename__ = "container_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    vessel_id: Mapped[int] = mapped_column(ForeignKey("vessel_calls.id"), index=True)
    container_no: Mapped[str] = mapped_column(String(20), unique=True)
    iso_type: Mapped[str] = mapped_column(String(10))
    cargo_class: Mapped[str] = mapped_column(String(30))
    weight_t: Mapped[float] = mapped_column(Float)
    customs_status: Mapped[str] = mapped_column(String(20), default="pending")
    seal_status: Mapped[str] = mapped_column(String(20), default="intact")
    check_state: Mapped[str] = mapped_column(String(20), default="pending")
    vessel: Mapped[VesselCall] = relationship(back_populates="containers")
    gates: Mapped[list["GateEvent"]] = relationship(back_populates="container", cascade="all, delete-orphan")

class GateEvent(Base):
    __tablename__ = "gate_events"
    __table_args__ = (UniqueConstraint("container_id", "event_ref", name="uq_gate_event_ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    container_id: Mapped[int] = mapped_column(ForeignKey("container_checks.id"), index=True)
    event_ref: Mapped[str] = mapped_column(String(40))
    gate_code: Mapped[str] = mapped_column(String(20))
    event_type: Mapped[str] = mapped_column(String(24))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dwell_min: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    note: Mapped[str] = mapped_column(String(240), default="")
    container: Mapped[ContainerCheck] = relationship(back_populates="gates")

class DelayCase(Base):
    __tablename__ = "delay_cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    vessel_id: Mapped[int] = mapped_column(ForeignKey("vessel_calls.id"), index=True)
    case_no: Mapped[str] = mapped_column(String(40), unique=True)
    requested_level: Mapped[str] = mapped_column(String(20), default="pending")
    final_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    reason: Mapped[str] = mapped_column(Text, default="")
    feature_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    exception_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    vessel: Mapped[VesselCall] = relationship(back_populates="cases")
    actions: Mapped[list["DispatchAction"]] = relationship(back_populates="case", cascade="all, delete-orphan")

class DispatchAction(Base):
    __tablename__ = "dispatch_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("delay_cases.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(32))
    assignee: Mapped[str] = mapped_column(String(80))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    instruction: Mapped[str] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    case: Mapped[DelayCase] = relationship(back_populates="actions")

class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("delay_cases.id"), index=True)
    job_type: Mapped[str] = mapped_column(String(32), default="delay_triage")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    input_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
