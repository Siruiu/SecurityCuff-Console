import time
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.contracts import Observation, Assessment, Event, Intervention
from backend.store import Store

ORIGIN = "http://testserver"


@pytest.fixture
def client(tmp_path):
    settings = {"database": str(tmp_path / "test.sqlite"), "viewer_password": "test-viewer-only",
        "operator_password": "test-operator-only", "cookie_secret": "test-only-cookie-key-0000000000000000",
        "allowed_origins": [ORIGIN], "secure_cookie": False, "interval": 0.04, "session_frames": 1000}
    with TestClient(create_app(settings)) as c:
        c.headers["origin"] = ORIGIN
        assert c.post("/api/login", json={"role": "operator", "password": "test-operator-only"}).status_code == 200
        for _ in range(100):
            if c.get("/api/state").json()["live"]:
                break
            time.sleep(.01)
        yield c


def command(client, **kw):
    o = client.get("/api/state").json()["live"]["observation"]
    return {"request_id": str(uuid4()), "session_id": o["session_id"], "frame_id": o["frame_id"], "action": "pause", "reason": "test", **kw}


def wait_result(client, rid):
    for _ in range(100):
        commands = client.get("/api/state").json()["interventions"]
        cmd = next(c for c in commands if c["request_id"] == rid)
        if cmd["status"] in ("executed", "failed", "rejected"):
            return cmd
        time.sleep(.01)
    pytest.fail("no execution receipt")


def test_contracts_and_frame_correlation(client):
    state = client.get("/api/state").json()
    f = state["live"]
    o = Observation(**f["observation"])
    assert len(f["assessments"]) == 2
    for value in f["assessments"]:
        a = Assessment(**value)
        assert a.frame_id == o.frame_id and a.session_id == o.session_id
        assert a.action_id == o.candidate_action["action_id"]
        assert "not probability" in a.score_meaning
    image = client.get(o.visual_ref)
    assert image.status_code == 200 and f"FRAME {o.frame_id:06d}" in image.text
    replay = client.get(f"/api/sessions/{o.session_id}/frames/{o.frame_id}").json()
    assert replay["historical"] and replay["live"] == f
    for e in state["events"]:
        Event(**e)
        assert client.get(f'/api/sessions/{e["session_id"]}/frames/{e["frame_id"]}').status_code == 200


def test_auth_role_origin_and_schema(client):
    client.cookies.clear()
    assert client.get("/api/state").status_code == 401
    assert client.get("/healthz").status_code == 200
    assert client.post("/api/login", json={"role": "viewer", "password": "test-viewer-only"}).status_code == 200
    assert client.post("/api/interventions", json=command(client)).status_code == 403
    assert client.post("/api/faults", json={"target":"capture", "mode":"freeze"}).status_code == 403
    assert client.post("/api/logout", json={}, headers={"origin":"https://attacker.invalid"}).status_code == 403
    assert client.get("/api/state").headers["cache-control"] == "no-store"


def test_intervention_transitions_and_idempotency(client):
    value = command(client)
    first = client.post("/api/interventions", json=value).json()
    assert first["status"] == "accepted"
    assert [t["status"] for t in first["transitions"]] == ["requested", "accepted"]
    assert client.post("/api/interventions", json=value).json()["request_id"] == first["request_id"]
    assert client.post("/api/interventions", json={**value,"reason":"different"}).status_code == 409
    result = wait_result(client, value["request_id"])
    Intervention(**result)
    assert result["status"] == "executed"
    assert [t["status"] for t in result["transitions"]] == ["requested", "accepted", "executed"]
    assert len([c for c in client.get("/api/state").json()["interventions"] if c["request_id"] == value["request_id"]]) == 1


def test_execution_failure(client):
    client.post("/api/faults", json={"target":"executor","mode":"fail_next"})
    value = command(client)
    client.post("/api/interventions", json=value)
    assert wait_result(client, value["request_id"])["status"] == "failed"


@pytest.mark.parametrize("mode", ["timeout", "disconnected"])
def test_algorithm_faults_are_visible_without_stopping_capture(client, mode):
    before = client.get("/api/state").json()["metrics"]["captured_frames"]
    client.post("/api/faults", json={"target":"action-consistency","mode":mode})
    time.sleep(.3)
    state = client.get("/api/state").json()
    a = next(a for a in state["live"]["assessments"] if a["algorithm_id"] == "action-consistency")
    assert a["health"] == mode and a["score"] is None and a["suggested_action"] is None
    assert state["metrics"]["captured_frames"] > before
    assert any(e["kind"] == "algorithm_health" for e in state["events"])
    client.post("/api/faults", json={"target":"action-consistency","mode":"normal"})


def test_historical_or_missing_frame_rejected(client):
    for overrides in ({"session_id":"old-session"},{"frame_id":99999}):
        r = client.post("/api/interventions", json=command(client, **overrides))
        assert r.json()["status"] == "rejected"


def test_stale_capture_disables_execution_and_recovers(client):
    value = command(client)
    client.post("/api/faults", json={"target":"capture","mode":"freeze"})
    time.sleep(2.1)
    assert client.post("/api/interventions", json=value).json()["status"] == "rejected"
    client.post("/api/faults", json={"target":"capture","mode":"normal"})
    time.sleep(.1)
    assert client.get("/healthz").status_code == 200


def test_resume_rejects_expired_assessment_before_observation_stale(client):
    value = command(client, action="resume")
    client.post("/api/faults", json={"target":"capture","mode":"freeze"})
    time.sleep(1.65)
    r = client.post("/api/interventions", json=value).json()
    assert r["status"] == "rejected"
    assert "unexpired" in r["result"]


def test_websocket_heartbeat_reconnect_capture_independent(client):
    with client.websocket_connect("/api/ws", headers={"origin":ORIGIN}) as ws:
        before = ws.receive_json()["sequence"]
        ws.send_json({"type":"ping","client_time":1234})
        for _ in range(10):
            m = ws.receive_json()
            if m["type"] == "pong":
                assert m["client_time"] == 1234
                break
        else:
            pytest.fail("no heartbeat pong")
    time.sleep(.15)
    with client.websocket_connect("/api/ws", headers={"origin":ORIGIN}) as ws:
        assert ws.receive_json()["sequence"] > before


def test_replay_does_not_show_future_execution(client):
    value = command(client)
    before = client.get(f'/api/sessions/{value["session_id"]}/frames/{value["frame_id"]}').json()
    client.post("/api/interventions", json=value)
    wait_result(client, value["request_id"])
    after = client.get(f'/api/sessions/{value["session_id"]}/frames/{value["frame_id"]}').json()
    assert before == after


def test_restart_marks_interrupted_and_retention(tmp_path):
    path = tmp_path/"db.sqlite"
    store = Store(path, keep_sessions=2)
    for n in range(4):
        store.session({"session_id":str(n),"status":"live" if n==3 else "closed"})
    store.close()
    store = Store(path, keep_sessions=2)
    assert store.sessions()[0]["status"] == "interrupted"
    assert store.cleanup("3") == 2
    assert len(store.sessions()) == 2
    store.close()


def test_restart_never_reexecutes_accepted_command(tmp_path):
    from backend.engine import Engine
    store = Store(tmp_path/"db.sqlite")
    store.session({"session_id":"old","status":"closed"})
    store.command({"request_id":"old-command","session_id":"old","status":"accepted","result":None,
                   "transitions":[{"status":"accepted","at":time.time()}]})
    engine = Engine(store,"test")
    assert store.get_command("old-command")["status"] == "unknown"
    assert engine.paused is True and not engine.pending
    store.close()
