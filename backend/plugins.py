import asyncio
import time
from uuid import uuid4
from .contracts import Assessment, Observation


class GeometryGuard:
    """Route A: observation-only geometric clearance rule, no ML/runtime binding."""
    id = "geometry-guard"
    version = "1.0.0-sim"
    meaning = "clearance severity index [0,1]; uncalibrated, not probability"

    async def assess(self, observation: Observation) -> Assessment:
        started = time.perf_counter()
        await asyncio.sleep(0.006)
        score = round(max(0, 1 - observation.robot_state["clearance_m"] / 1.5), 3)
        return self.result(observation, score, started, "proximity")

    def result(self, obs, score, started, risk_type):
        now = time.time()
        return Assessment(assessment_id=str(uuid4()), algorithm_id=self.id,
            algorithm_version=self.version, session_id=obs.session_id, frame_id=obs.frame_id,
            action_id=(obs.candidate_action or {}).get("action_id"), risk_type=risk_type,
            score=score, score_meaning=self.meaning, assessed_at=now, valid_until=now + 1.5,
            suggested_action="pause" if score >= 0.72 else None,
            processing_ms=(time.perf_counter() - started) * 1000, health="ok")


class ActionConsistency(GeometryGuard):
    """Route B: candidate-action / task-context check, replaceable by a model adapter."""
    id = "action-consistency"
    version = "1.0.0-sim"
    meaning = "action/context mismatch index [0,1]; uncalibrated, not probability"

    async def assess(self, observation: Observation) -> Assessment:
        started = time.perf_counter()
        await asyncio.sleep(0.012)
        action = observation.candidate_action or {}
        allowed = observation.task_step.get("allowed_zones", ["work"])
        score = 0.9 if action.get("target_zone") not in allowed else 0.12
        return self.result(observation, score, started, "action_context")


PLUGINS = (GeometryGuard(), ActionConsistency())
