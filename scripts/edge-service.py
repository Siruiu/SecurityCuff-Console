"""User service lifecycle. Run on ARM64 after source sync, dependency and web delivery.

Does not read or alter cpolar configuration. Never prints credentials.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import time

root = Path(__file__).resolve().parents[1]
home = Path.home()
state = home / ".local/state/safecuff-console"
share = home / ".local/share/safecuff-console"
config = state / "config.json"
unit = home / ".config/systemd/user/safecuff-console.service"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("action", choices=["install", "start", "stop", "restart", "status"])
parser.add_argument("--takeover-test", action="store_true", help="replace only the known 20261116 test HTTP handler")
args = parser.parse_args()


def run(*cmd):
    subprocess.run(cmd, check=True)


def port_open():
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", 18080)) == 0


if args.action == "install":
    assert not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True).strip(), "worktree must be clean"
    revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    assert (share / "venv/bin/python").is_file(), "Install ARM64 Python dependencies first"
    web = share / "web/current"
    manifest = json.loads((web / "manifest.json").read_text())
    assert manifest["revision"] == revision, "Web artifact revision does not match source"
    import hashlib
    for filename, digest in manifest["sha256"].items():
        path = (web / filename).resolve()
        assert path.is_relative_to(web.resolve()), "unsafe artifact path"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, "Web artifact checksum mismatch"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state, 0o700)
    if not config.exists():
        value = json.loads((root / "config/example.json").read_text())
        value.update(device_id="rk3588-demo", database=str(state / "sessions.sqlite3"), static_dir=str(web),
            allowed_origins=["http://127.0.0.1:18080"], public_viewer=False, secure_cookie=True,
            viewer_password=secrets.token_urlsafe(16), operator_password=secrets.token_urlsafe(16),
            cookie_secret=secrets.token_hex(32))
        fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(value, f, indent=2)
    assert config.stat().st_mode & 0o077 == 0, "Config must have mode 600"
    if args.takeover_test and port_open():
        test_dir = home / ".local/state/safecuff-web-test-20261116"
        pid = int((test_dir / "web.pid").read_text())
        proc = Path(f"/proc/{pid}")
        cmdline = (proc / "cmdline").read_bytes().split(b"\0")
        assert str(test_dir / "server.py").encode() in cmdline, "Listener is not the known test handler; refusing takeover"
        assert proc.stat().st_uid == os.getuid(), "Unexpected process owner"
        assert (proc / "cwd").resolve() == test_dir, "Unexpected process directory"
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if not port_open():
                break
            time.sleep(.1)
        assert not port_open(), "Port still in use; refusing to stop another process"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(f'''[Unit]
Description=SafeCuff simulation console (no robot control)
After=network.target

[Service]
WorkingDirectory={root}
Environment=SAFECUFF_CONFIG={config}
Environment=SAFECUFF_REVISION={revision}
ExecStart={share}/venv/bin/python -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 18080 --no-access-log --ws-ping-interval 10 --ws-ping-timeout 20
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
MemoryMax=384M
CPUQuota=100%
StandardOutput=journal
StandardError=journal
LogRateLimitIntervalSec=30
LogRateLimitBurst=20

[Install]
WantedBy=default.target
''')
    run("systemctl", "--user", "daemon-reload")
    run("systemctl", "--user", "enable", "--now", "safecuff-console.service")
    run("systemctl", "--user", "restart", "safecuff-console.service")
    print("Installed simulation console; external config retained; cpolar unchanged.")
else:
    run("systemctl", "--user", args.action, "safecuff-console.service")
