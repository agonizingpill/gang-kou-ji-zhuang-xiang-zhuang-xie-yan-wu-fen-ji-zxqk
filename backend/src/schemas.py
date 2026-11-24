from datetime import datetime
from pydantic import BaseModel, Field

class LoginIn(BaseModel):
    username: str
    password: str

class VesselIn(BaseModel):
    call_no: str = Field(min_length=3, max_length=40)
    vessel_name: str
    terminal: str
    berth: str
    eta: datetime
    etd: datetime
    notes: str = ""

class ContainerIn(BaseModel):
    vessel_id: int
    container_no: str
    iso_type: str
    cargo_class: str
    weight_t: float = Field(gt=0)
    customs_status: str = "pending"
    seal_status: str = "intact"

class GateIn(BaseModel):
    container_id: int
    event_ref: str
    gate_code: str
    event_type: str
    event_time: datetime
    dwell_min: float = Field(ge=0)
    note: str = ""

class DelayCaseIn(BaseModel):
    vessel_id: int
    case_no: str
    reason: str

class DispatchIn(BaseModel):
    action_type: str
    assignee: str
    due_at: datetime
    instruction: str

class GradeExplanationIn(BaseModel):
    dispatch_action_id: int | None = None

class CustomsUpdate(BaseModel):
    customs_status: str
