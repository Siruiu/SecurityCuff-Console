"""Version 1 contracts. Wall times are UTC seconds; deadlines use edge monotonic time."""
from typing import Literal, Protocol
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observation(Contract):
    schema_version: Literal[1] = 1
    device_id: str
    session_id: str
    source_id: str = "sim-camera"
    stream_epoch: str
    frame_id: int
    captured_at: float
    received_at: float
    clock_source: str = "edge-system-utc; simulated capture; monotonic deadlines"
    visual_ref: str
    robot_state: dict
    task_step: dict
    candidate_action: dict | None = None


class Assessment(Contract):
    assessment_id: str
    algorithm_id: str
    algorithm_version: str
    config_version: str = "demo-v1"
    session_id: str
    frame_id: int
    action_id: str | None = None
    risk_type: str
    score: float | None
    score_meaning: str
    assessed_at: float
    valid_until: float
    suggested_action: str | None
    processing_ms: float
    health: Literal["ok", "timeout", "disconnected", "error"]


class InterventionRequest(Contract):
    request_id: UUID
    session_id: str
    frame_id: int
    action: Literal["pause", "resume"]
    reason: str = Field(min_length=1, max_length=200)


class Intervention(Contract):
    request_id: str
    session_id: str
    frame_id: int
    source: str
    action: str
    reason: str
    status: Literal["requested", "accepted", "rejected", "executed", "failed", "unknown"]
    transitions: list[dict]
    result: str | None = None


class Event(Contract):
    event_id: str
    session_id: str
    frame_id: int
    at: float
    kind: str
    level: str
    message: str
    assessment_id: str | None = None
    request_id: str | None = None
    algorithm_config: dict
    log_ref: str


class Session(Contract):
    session_id: str
    device_id: str
    started_at: float
    ended_at: float | None = None
    status: Literal["live", "closed", "interrupted"]
    revision: str
    algorithm_config: dict


class Algorithm(Protocol):
    id: str
    version: str
    async def assess(self, observation: Observation) -> Assessment: ...
