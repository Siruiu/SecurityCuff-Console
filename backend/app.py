import asyncio
import base64
from contextlib import asynccontextmanager, suppress
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .contracts import InterventionRequest
from .engine import Engine
from .store import Store


class Login(BaseModel):
    role: Literal["viewer", "operator"]
    password: str = Field(max_length=200)


class Fault(BaseModel):
    target: str
    mode: Literal["normal", "timeout", "disconnected", "freeze", "fail_next"]


def create_app(settings=None):
    if settings is None:
        settings = json.loads(Path(os.environ["SAFECUFF_CONFIG"]).read_text())
    if not all(settings.get(k) for k in ("viewer_password", "operator_password", "cookie_secret")):
        raise ValueError("external passwords and cookie secret are required")
    revision = os.getenv("SAFECUFF_REVISION", settings.get("revision", "development"))
    allowed = settings.get("allowed_origins", [])
    secret = settings["cookie_secret"].encode()
    attempts = []
    mutations = []

    def sign(role):
        raw = f"{role}:{int(time.time()+28800)}:{secrets.token_hex(12)}"
        mac = hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(f"{raw}:{mac}".encode()).decode()

    def verify(token):
        try:
            raw, mac = base64.urlsafe_b64decode(token).decode().rsplit(":", 1)
            role, expiry, _ = raw.split(":")
            if (role in ("viewer", "operator") and int(expiry) > time.time()
                    and hmac.compare_digest(mac, hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest())):
                return role
        except Exception:
            pass
        return None

    def auth(request, operator=False):
        role = verify(request.cookies.get("safecuff_session", ""))
        if not role:
            raise HTTPException(401, "请登录")
        if operator and role != "operator":
            raise HTTPException(403, "需要操作员权限")
        return role

    def origin_ok(origin):
        return origin in allowed

    @asynccontextmanager
    async def lifespan(app):
        store = Store(Path(settings["database"]), settings.get("quota_mb", 128), settings.get("keep_sessions", 12))
        engine = Engine(store, revision, settings.get("device_id", "rk3588-demo"), settings.get("interval", 0.5), settings.get("session_frames", 1200))
        app.state.engine = engine
        store.cleanup(engine.session["session_id"])
        task = asyncio.create_task(engine.run())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await engine.close()
            store.close()

    app = FastAPI(title="SafeCuff simulated console", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request, call_next):
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD"):
            if not origin_ok(request.headers.get("origin")):
                return Response("Origin denied", status_code=403)
            if request.url.path in ("/api/interventions", "/api/faults"):
                now = time.monotonic()
                mutations[:] = [t for t in mutations if now-t < 60]
                if len(mutations) >= 120:
                    return Response('"操作频率过高，请稍后重试"', status_code=429, media_type="application/json")
                mutations.append(now)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith("/api/") or request.url.path == "/healthz":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    async def health():
        e = app.state.engine
        age = time.monotonic() - e.last_capture_mono if e.last_capture_mono else 999
        ok = age < 3 and e.metrics["recording_health"] == "ok"
        return Response(json.dumps({"service": "safecuff-console", "mode": "simulation-only", "version": "0.1.0",
            "revision": revision, "status": "ok" if ok else "degraded", "data_age_ms": round(age*1000)}),
            status_code=200 if ok else 503, media_type="application/json")

    @app.post("/api/login")
    async def login(value: Login, response: Response):
        now = time.monotonic()
        attempts[:] = [t for t in attempts if now-t < 60]
        if len(attempts) >= 30:
            raise HTTPException(429, "登录尝试过多，请稍后重试")
        attempts.append(now)
        if not hmac.compare_digest(value.password.encode(), settings[value.role + "_password"].encode()):
            raise HTTPException(401, "密码错误")
        response.set_cookie("safecuff_session", sign(value.role), httponly=True,
                            secure=settings.get("secure_cookie", True), samesite="strict", max_age=28800)
        return {"role": value.role}

    @app.post("/api/logout")
    async def logout(response: Response):
        response.delete_cookie("safecuff_session")
        return {"ok": True}

    @app.get("/api/me")
    async def me(request: Request):
        return {"role": auth(request), "revision": revision}

    @app.get("/api/state")
    async def state(request: Request):
        auth(request)
        return app.state.engine.state()

    @app.get("/api/sessions")
    async def sessions(request: Request):
        auth(request)
        return app.state.engine.store.sessions()

    @app.get("/api/sessions/{sid}/frames")
    async def frames(sid: str, request: Request):
        auth(request)
        return app.state.engine.store.frame_index(sid)

    def get_frame(sid, fid):
        frame = app.state.engine.store.frame(sid, fid)
        if not frame:
            raise HTTPException(404, "帧不存在或已按配额清理")
        return frame

    @app.get("/api/sessions/{sid}/frames/{fid}")
    async def frame(sid: str, fid: int, request: Request):
        auth(request)
        e = app.state.engine
        f = get_frame(sid, fid)
        cutoff = f.get("recorded_at", f["observation"]["captured_at"])
        return {"live": f, "events": e.store.events(sid, fid, cutoff),
                "interventions": e.store.commands(sid, cutoff), "historical": True}

    @app.get("/api/sessions/{sid}/frames/{fid}/image.svg")
    async def image(sid: str, fid: int, request: Request):
        auth(request)
        f = get_frame(sid, fid)["observation"]
        x = float(f["robot_state"]["object_x"])
        # Only typed/numeric data is interpolated, never operator text or arbitrary SVG.
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450" viewBox="0 0 800 450">
        <defs><pattern id="g" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M 40 0 L 0 0 0 40" fill="none" stroke="#20333b"/></pattern></defs>
        <rect width="800" height="450" fill="#0c1c24"/><rect width="800" height="450" fill="url(#g)"/>
        <rect x="540" y="95" width="190" height="270" rx="8" stroke="#f3ae58" stroke-dasharray="8" fill="#60472b" fill-opacity=".35"/>
        <text x="560" y="125" fill="#f3ae58" font-family="monospace">RESTRICTED</text>
        <path d="M80 330 L250 220 L450 280 L650 220" fill="none" stroke="#3dbab1" stroke-dasharray="6"/>
        <circle cx="{x}" cy="250" r="40" fill="#1f777d" stroke="#69e5d3" stroke-width="3"/>
        <path d="M{x-20} 250 h40 M{x} 230 v40" stroke="#a6fff1"/>
        <rect x="35" y="35" width="240" height="40" fill="#14323d"/><text x="50" y="61" fill="#a6fff1" font-family="monospace">SIMULATED / FRAME {fid:06d}</text>
        <text x="40" y="410" fill="#9aafbd" font-family="monospace">CLEARANCE {f['robot_state']['clearance_m']:.3f} m | SYNTHETIC EVIDENCE</text></svg>'''
        return Response(svg, media_type="image/svg+xml")

    @app.post("/api/interventions")
    async def intervention(value: InterventionRequest, request: Request):
        role = auth(request, True)
        try:
            return app.state.engine.request(value, role)
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/faults")
    async def faults(value: Fault, request: Request):
        auth(request, True)
        e = app.state.engine
        if value.target in e.config and value.mode in ("normal", "timeout", "disconnected"):
            e.config[value.target] = {**e.config[value.target], "mode": value.mode}
        elif value.target == "capture" and value.mode in ("freeze", "normal"):
            e.freeze_until = time.monotonic()+8 if value.mode == "freeze" else 0
        elif value.target == "executor" and value.mode in ("fail_next", "normal"):
            e.fail_next = value.mode == "fail_next"
        else:
            raise HTTPException(422, "不支持的故障配置")
        e.event("fault_injection", f"{value.target}: {value.mode}", "warning")
        return {"ok": True}

    @app.websocket("/api/ws")
    async def websocket(ws: WebSocket):
        token = ws.cookies.get("safecuff_session", "")
        if not origin_ok(ws.headers.get("origin")) or not verify(token):
            await ws.close(code=1008)
            return
        e = app.state.engine
        if len(e.subscribers) >= 16:
            await ws.close(code=1013)
            return
        await ws.accept()
        q = asyncio.Queue(maxsize=1)
        e.subscribers.add(q)
        send_lock = asyncio.Lock()

        async def send():
            while True:
                if not verify(token):
                    await ws.close(code=1008)
                    return
                async with send_lock:
                    await asyncio.wait_for(ws.send_json(e.state()), 5)
                await q.get()

        async def receive():
            while True:
                message = await asyncio.wait_for(ws.receive_json(), 20)
                if message.get("type") == "ping":
                    async with send_lock:
                        await asyncio.wait_for(ws.send_json({"type": "pong", "client_time": message.get("client_time"), "server_time": time.time()}), 5)

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            e.subscribers.discard(q)
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with suppress(Exception):
                await ws.close()

    @app.get("/api/clock")
    async def clock(request: Request):
        auth(request)
        return {"server_time": time.time()}

    static = Path(settings.get("static_dir", "frontend/dist"))
    if static.is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/")
        async def home():
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-store"})
    return app
