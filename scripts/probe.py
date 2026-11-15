"""API / WebSocket acceptance probe. Credentials are read from config or environment, never argv."""
import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import statistics
import time
from urllib.parse import urlparse
from uuid import uuid4
import httpx
from websockets.asyncio.client import connect

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--origin")
parser.add_argument("--config", type=Path)
parser.add_argument("--seconds", type=int, default=60)
parser.add_argument("--output", type=Path)
parser.add_argument("--exercise", action="store_true")
args = parser.parse_args()
origin = args.origin or args.url.rstrip("/")
config = json.loads(args.config.read_text()) if args.config else {}
password = config.get("operator_password") or os.environ["DEMO_PASSWORD"]
viewer_password = config.get("viewer_password") or os.getenv("DEMO_VIEWER_PASSWORD")


def pct(values, p):
    return round(sorted(values)[max(0, math.ceil(len(values)*p)-1)], 2) if values else None


async def main():
    result = {"url": args.url, "started_at": time.time(), "checks": {}}
    checks = result["checks"]
    async with httpx.AsyncClient(base_url=args.url, timeout=20, headers={"Origin":origin}, trust_env=False) as client:
        assert (await client.get("/api/state")).status_code == 401
        checks["anonymous_denied"] = True
        r = await client.post("/api/login", json={"role":"operator","password":password})
        r.raise_for_status()
        cookie = "safecuff_session=" + client.cookies.get("safecuff_session")
        client.headers["Cookie"] = cookie  # Local edge HTTP probe explicitly tests a Secure HTTPS cookie.
        checks["login"] = True
        if viewer_password:
            async with httpx.AsyncClient(base_url=args.url, timeout=20, headers={"Origin":origin}, trust_env=False) as viewer:
                (await viewer.post("/api/login", json={"role":"viewer","password":viewer_password})).raise_for_status()
                viewer.headers["Cookie"] = "safecuff_session=" + viewer.cookies.get("safecuff_session")
                assert (await viewer.post("/api/faults", json={"target":"executor","mode":"fail_next"})).status_code == 403
                checks["viewer_write_denied"] = True
        offsets = []
        for _ in range(5):
            start = time.time()
            r = await client.get("/api/clock")
            end = time.time()
            r.raise_for_status()
            offsets.append(((end-start)*1000, r.json()["server_time"]-(start+end)/2))
        best_rtt, offset = min(offsets)
        result["clock"] = {"best_http_rtt_ms":round(best_rtt,2),"edge_minus_client_ms":round(offset*1000,2),"one_way_estimate_uncertainty_ms":round(best_rtt/2,2)}
        ws_url = args.url.replace("https://","wss://").replace("http://","ws://").rstrip("/")+"/api/ws"

        if args.exercise:
            async def state():
                r=await client.get("/api/state");r.raise_for_status();return r.json()
            async def fault(target, mode):
                (await client.post("/api/faults",json={"target":target,"mode":mode})).raise_for_status()
            for mode in ("timeout","disconnected"):
                await fault("action-consistency",mode)
                await asyncio.sleep(1)
                a=(await state())["live"]["assessments"][1]
                assert a["health"]==mode and a["score"] is None
                checks["plugin_"+mode]=True
            await fault("action-consistency","normal")
            await asyncio.sleep(1)
            await fault("executor","fail_next")
            s=await state();o=s["live"]["observation"]
            command={"request_id":str(uuid4()),"session_id":o["session_id"],"frame_id":o["frame_id"],"action":"pause","reason":"acceptance probe (simulator only)"}
            r=await client.post("/api/interventions",json=command);r.raise_for_status()
            assert r.json()["status"]=="accepted"
            (await client.post("/api/interventions",json=command)).raise_for_status()
            await asyncio.sleep(1)
            c=next(c for c in (await state())["interventions"] if c["request_id"]==command["request_id"])
            assert c["status"]=="failed"
            checks["failed_receipt_and_idempotency"]=True
            command["request_id"]=str(uuid4());s=await state();o=s["live"]["observation"]
            command.update(session_id=o["session_id"],frame_id=o["frame_id"])
            (await client.post("/api/interventions",json=command)).raise_for_status()
            await asyncio.sleep(1)
            assert next(c for c in (await state())["interventions"] if c["request_id"]==command["request_id"])["status"]=="executed"
            checks["execution_confirmation"]=True
            e=(await state())["events"][0]
            f=await client.get(f'/api/sessions/{e["session_id"]}/frames/{e["frame_id"]}');f.raise_for_status()
            assert f.json()["live"]["observation"]["frame_id"]==e["frame_id"]
            image=await client.get(f.json()["live"]["observation"]["visual_ref"]);image.raise_for_status()
            assert image.headers["content-type"].startswith("image/svg+xml")
            checks["event_original_frame_https_image"]=True
            await fault("capture","freeze")
            await asyncio.sleep(3.2)
            assert (await client.get("/healthz")).status_code==503
            command["request_id"]=str(uuid4())
            assert (await client.post("/api/interventions",json=command)).json()["status"]=="rejected"
            await fault("capture","normal")
            await asyncio.sleep(1)
            assert (await client.get("/healthz")).status_code==200
            checks["stale_rejection_and_recovery"]=True

        processing, transfer, intervals, pings = [], [], [], []
        sequence_gaps=0
        last_seq=None
        first_metrics=None
        last_metrics=None
        snapshots=0
        fid_before=None
        async with connect(ws_url,origin=origin,additional_headers={"Cookie":cookie},open_timeout=20,ping_interval=10,ping_timeout=20) as ws:
            checks["websocket_upgrade"] = ws.response.status_code == 101
            start=time.monotonic();last_received=None;next_ping=0
            while time.monotonic()-start < args.seconds:
                if time.monotonic()>=next_ping:
                    await ws.send(json.dumps({"type":"ping","client_time":time.monotonic()}));next_ping=time.monotonic()+3
                message=json.loads(await asyncio.wait_for(ws.recv(),timeout=15))
                if message["type"]=="pong":
                    pings.append((time.monotonic()-message["client_time"])*1000);continue
                received=time.time()
                if last_received is not None:intervals.append((received-last_received)*1000)
                last_received=received
                if last_seq is not None:sequence_gaps+=max(0,message["sequence"]-last_seq-1)
                last_seq=message["sequence"]
                snapshots+=1
                transfer.append((received+offset-message["server_sent_at"])*1000)
                processing.append(message["live"]["processing_ms"])
                first_metrics=first_metrics or message["metrics"]
                last_metrics=message["metrics"]
                fid_before=message["metrics"]["captured_frames"]
        duration=time.monotonic()-start
        await asyncio.sleep(3)
        async with connect(ws_url,origin=origin,additional_headers={"Cookie":cookie},open_timeout=20) as ws:
            after=json.loads(await ws.recv())
            assert after["metrics"]["captured_frames"]>fid_before
            checks["reconnect_and_capture_without_browser"]=True
        result.update(duration_s=round(duration,2),snapshots=snapshots,sequence_gaps=sequence_gaps,
            processing_ms={"p50":pct(processing,.5),"p95":pct(processing,.95),"max":round(max(processing),2)},
            transfer_estimate_ms={"p50":pct(transfer,.5),"p95":pct(transfer,.95),"min":round(min(transfer),2)},
            heartbeat_rtt_ms={"count":len(pings),"p50":pct(pings,.5),"p95":pct(pings,.95)},
            receive_interval_ms={"p50":pct(intervals,.5),"p95":pct(intervals,.95),"max":round(max(intervals),2)},
            first_metrics=first_metrics,last_metrics=last_metrics,revision=after["session"]["revision"])
    assert pings, "no application heartbeat acknowledged"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


asyncio.run(main())
