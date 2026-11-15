import asyncio
import math
import time
from uuid import uuid4
from .contracts import Observation, Assessment, Event, Session, Intervention
from .plugins import PLUGINS


class Engine:
    def __init__(self, store, revision, device_id="rk3588-demo", interval=0.5, session_frames=1200):
        self.store, self.revision, self.device_id = store, revision, device_id
        self.interval, self.session_frames = interval, session_frames
        self.config = {p.id: {"version": p.version, "mode": "normal"} for p in PLUGINS}
        self.latest = None
        self.frame_id = 0
        self.sequence = 0
        self.task_tick = 0
        self.paused = True  # Restart never resumes even the simulated executor automatically.
        self.freeze_until = 0
        self.fail_next = False
        self.last_capture_mono = 0
        self.started_mono = time.monotonic()
        self.subscribers = set()
        self.pending = set()
        self.rotate_requested = False
        self.metrics = {"captured_frames": 0, "scheduler_missed": 0, "subscriber_drops": 0,
                        "recording_errors": 0, "recording_health": "ok", "pruned_sessions": 0}
        self.new_session()
        # Accepted commands from a previous process must never execute after restart.
        for s in store.sessions():
            for cmd in store.commands(s["session_id"]):
                if cmd["status"] == "accepted":
                    self.transition(cmd, "unknown", "service restarted before execution confirmation")

    def new_session(self):
        self.session = Session(session_id=str(uuid4()), device_id=self.device_id, started_at=time.time(),
            status="live", revision=self.revision, algorithm_config=self.config.copy()).model_dump()
        self.store.session(self.session)
        self.frame_id = 0
        self.latest = None

    def event(self, kind, message, level="info", assessment_id=None, request_id=None):
        if not self.latest:
            return
        event = Event(event_id=str(uuid4()), session_id=self.session["session_id"], frame_id=self.frame_id,
            at=time.time(), kind=kind, level=level, message=message, assessment_id=assessment_id,
            request_id=request_id, algorithm_config=self.config.copy(), log_ref=f"event:{kind}").model_dump()
        self.store.event(event)

    async def run_plugin(self, plugin, obs):
        started = time.perf_counter()
        mode = self.config[plugin.id]["mode"]
        try:
            if mode == "disconnected":
                raise ConnectionError()
            async def invoke():
                if mode == "timeout":
                    await asyncio.sleep(0.5)
                return await plugin.assess(obs)
            return await asyncio.wait_for(invoke(), timeout=0.12)
        except Exception as exc:
            # Python 3.10 asyncio.TimeoutError is distinct from built-in TimeoutError.
            health = "timeout" if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) else "disconnected" if isinstance(exc, ConnectionError) else "error"
            return Assessment(assessment_id=str(uuid4()), algorithm_id=plugin.id, algorithm_version=plugin.version,
                session_id=obs.session_id, frame_id=obs.frame_id, action_id=(obs.candidate_action or {}).get("action_id"),
                risk_type="unavailable", score=None, score_meaning=plugin.meaning, assessed_at=time.time(),
                valid_until=time.time(), suggested_action=None, processing_ms=(time.perf_counter()-started)*1000, health=health)

    async def tick(self):
        if time.monotonic() < self.freeze_until:
            return
        if self.frame_id >= self.session_frames or self.rotate_requested:
            self.session.update(status="closed", ended_at=time.time())
            self.store.session(self.session)
            self.new_session()
            self.rotate_requested = False
            self.metrics["pruned_sessions"] += self.store.cleanup(self.session["session_id"])
        started = time.perf_counter()
        self.frame_id += 1
        fid, sid = self.frame_id, self.session["session_id"]
        if not self.paused:
            self.task_tick += 1
        captured = time.time()
        clearance = round(0.9 + 0.75 * math.sin(fid / 13), 3)
        zone = "restricted" if fid % 48 in range(32, 40) else "work"
        obs = Observation(device_id=self.device_id, session_id=sid, stream_epoch=sid, frame_id=fid,
            captured_at=captured, received_at=time.time(), visual_ref=f"/api/sessions/{sid}/frames/{fid}/image.svg",
            robot_state={"mode": "SIMULATION", "paused": self.paused, "clearance_m": clearance,
                         "speed_mps": 0 if self.paused else 0.15, "object_x": 140 + (fid * 7) % 360},
            task_step={"task_id": "inspection-demo", "name": "工作区巡检", "step": (self.task_tick // 20) % 4 + 1,
                       "total": 4, "allowed_zones": ["work"], "label": ["观察", "接近目标", "核验路径", "返回"][self.task_tick // 20 % 4]},
            candidate_action={"action_id": f"{sid}:{fid}:candidate", "name": "move_to_zone", "target_zone": zone})
        assessments = [a.model_dump() for a in await asyncio.gather(*(self.run_plugin(p, obs) for p in PLUGINS))]
        previous = {a["algorithm_id"]: a for a in self.latest["assessments"]} if self.latest else {}
        self.latest = {"observation": obs.model_dump(), "assessments": assessments,
                       "processing_ms": (time.perf_counter()-started)*1000}
        self.last_capture_mono = time.monotonic()
        self.metrics["recording_health"] = "ok"
        self.metrics["captured_frames"] += 1
        for a in assessments:
            old = previous.get(a["algorithm_id"], {})
            if a["health"] != old.get("health", "ok"):
                self.event("algorithm_health", f'{a["algorithm_id"]}: {a["health"]}', "warning", a["assessment_id"])
            if a["suggested_action"] and not old.get("suggested_action"):
                self.event("suggestion", f'{a["algorithm_id"]} 建议暂停（未发送执行请求）', "warning", a["assessment_id"])
        if fid % 20 == 1:
            self.event("task", f'巡检步骤 {obs.task_step["step"]}: {obs.task_step["label"]}')
        self.latest["recorded_at"] = time.time()
        self.store.record(self.latest)
        if fid % 60 == 0:
            self.metrics["pruned_sessions"] += self.store.cleanup(sid)
            if self.store.size() > self.store.quota_mb * 1024**2 * 0.9:
                # Bound the active session too; oldest entire sessions are pruned next tick.
                self.rotate_requested = True

    async def run(self):
        while True:
            begin = time.monotonic()
            try:
                await self.tick()
            except Exception:
                self.metrics["recording_errors"] += 1
                self.metrics["recording_health"] = "error"
            self.sequence += 1
            for q in list(self.subscribers):
                if q.full():
                    q.get_nowait()
                    self.metrics["subscriber_drops"] += 1
                q.put_nowait(self.sequence)
            elapsed = time.monotonic() - begin
            if elapsed > self.interval:
                self.metrics["scheduler_missed"] += int(elapsed / self.interval)
            await asyncio.sleep(max(0.01, self.interval - elapsed))

    def state(self):
        return {"type": "snapshot", "sequence": self.sequence, "server_sent_at": time.time(),
                "live": self.latest, "session": self.session, "algorithm_config": self.config,
                "events": self.store.events(self.session["session_id"]),
                "interventions": self.store.commands(self.session["session_id"]),
                "metrics": {**self.metrics, "uptime_s": time.monotonic()-self.started_mono,
                    "data_age_ms": (time.monotonic()-self.last_capture_mono)*1000 if self.last_capture_mono else None,
                    "recording_bytes": self.store.size(), "quota_mb": self.store.quota_mb,
                    "subscribers": len(self.subscribers), "max_queue_depth": max([q.qsize() for q in self.subscribers] or [0])}}

    def transition(self, cmd, status, detail):
        cmd["status"] = status
        cmd["result"] = detail
        cmd["transitions"].append({"status": status, "at": time.time(), "detail": detail})
        self.store.command(cmd)

    def request(self, request, role):
        value = request.model_dump(mode="json")
        old = self.store.get_command(value["request_id"])
        if old:
            if any(old[k] != value[k] for k in ("session_id", "frame_id", "action", "reason")):
                raise ValueError("request_id already used with a different payload")
            return old
        cmd = Intervention(**value, source=f"web:{role}", status="requested", transitions=[]).model_dump()
        self.transition(cmd, "requested", "operator request; simulator only")
        fresh = self.latest and time.monotonic() - self.last_capture_mono < 2
        valid_frame = fresh and self.store.frame(value["session_id"], value["frame_id"])
        if (not fresh or value["session_id"] != self.session["session_id"] or not valid_frame
                or time.time() - valid_frame["observation"]["captured_at"] > 3
                or self.metrics["recording_health"] != "ok"):
            self.transition(cmd, "rejected", "stale observation, historical session or recorder unavailable")
        elif request.action == "resume" and (
            time.monotonic() - self.last_capture_mono >= 1.5
            or any(a["health"] != "ok" or a["suggested_action"] or a["valid_until"] <= time.time()
                   for a in self.latest["assessments"])
        ):
            self.transition(cmd, "rejected", "resume requires unexpired healthy assessments without active suggestions")
        elif sum(not t.done() for t in self.pending) >= 8:
            self.transition(cmd, "rejected", "simulator command queue full")
        else:
            self.transition(cmd, "accepted", "simulator accepted; execution not confirmed")
            fail = self.fail_next
            self.fail_next = False
            task = asyncio.create_task(self.execute(cmd, fail))
            self.pending.add(task)
            task.add_done_callback(self.pending.discard)
        self.event("intervention", f'{request.action}: {cmd["status"]}', request_id=cmd["request_id"])
        return cmd

    async def execute(self, cmd, fail):
        await asyncio.sleep(0.35)
        if fail:
            self.transition(cmd, "failed", "injected simulator execution failure; no confirmation")
        else:
            self.paused = cmd["action"] == "pause"
            self.transition(cmd, "executed", f'simulator state confirmed: paused={self.paused}')
        self.event("execution_receipt", cmd["result"], "error" if fail else "info", request_id=cmd["request_id"])

    async def close(self):
        for task in list(self.pending):
            task.cancel()
        await asyncio.gather(*self.pending, return_exceptions=True)
        for cmd in self.store.commands(self.session["session_id"]):
            if cmd["status"] == "accepted":
                self.transition(cmd, "unknown", "service shutdown before execution confirmation")
        self.session.update(status="closed", ended_at=time.time())
        self.store.session(self.session)
