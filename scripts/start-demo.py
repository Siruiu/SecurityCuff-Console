"""Run a local simulator and a reserved cpolar tunnel until Ctrl+C."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener, urlopen


ROOT = Path(__file__).resolve().parents[1]
LOOPBACK = build_opener(ProxyHandler({}))


def read_health(origin):
    open_request = LOOPBACK.open if origin.startswith("http://127.0.0.1:") else urlopen
    try:
        with open_request(origin + "/healthz", timeout=2) as response:
            health = json.load(response)
        return health if isinstance(health, dict) else {}
    except (OSError, ValueError):
        return {}


def wait_for_health(origin, process, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Process exited before {origin} was ready (exit {process.returncode})")
        health = read_health(origin)
        if health.get("service") == "safecuff-console" and health.get("status") == "ok":
            return
        time.sleep(0.5)
    raise RuntimeError(f"Health check timed out at {origin}/healthz")


def check_domain_available(public_origin):
    """Cooperative handoff check. cpolar still decides who can bind the domain."""
    try:
        with urlopen(public_origin + "/healthz", timeout=5):
            pass
    except HTTPError as exc:
        hostname = urlsplit(public_origin).hostname
        missing = f"Tunnel {hostname} not found".encode()
        if exc.code == 404 and missing in exc.read(4096):
            return
    except (URLError, OSError):
        raise RuntimeError("Could not check the shared domain. Check cpolar status before starting.") from None
    raise RuntimeError("The shared domain is already responding. Stop its current tunnel first.")


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpolar-config", type=Path, required=True, help="Existing private cpolar config")
    parser.add_argument("--public-origin", required=True, help="Reserved HTTPS address")
    parser.add_argument("--port", type=int, default=18080, help="Loopback port from the cpolar config")
    parser.add_argument("--cpolar-bin", default="cpolar", help="cpolar executable or path")
    parser.add_argument("--tunnel", help="Name to start from a config containing multiple tunnels")
    args = parser.parse_args()

    public = urlsplit(args.public_origin)
    if (public.scheme != "https" or not public.hostname or public.username is not None
            or public.path not in ("", "/") or public.query or public.fragment):
        parser.error("--public-origin must be an HTTPS origin without a path")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    public_origin = f"https://{public.netloc}"
    config = args.cpolar_config.expanduser().resolve()
    if not config.is_file():
        parser.error("cpolar configuration file was not found")
    if os.name == "posix" and config.stat().st_mode & 0o077:
        parser.error("Private cpolar configuration is group- or world-accessible; use chmod 600")
    cpolar = shutil.which(os.path.expanduser(args.cpolar_bin))
    if not cpolar:
        parser.error("cpolar executable was not found; install it or specify --cpolar-bin")
    if not (ROOT / "frontend/dist/index.html").is_file():
        parser.error("Build the frontend first: npm run build --prefix frontend")

    try:
        check_domain_available(public_origin)
    except RuntimeError as exc:
        parser.exit(1, f"{exc}\n")

    local_origin = f"http://127.0.0.1:{args.port}"
    settings = json.loads((ROOT / "config/example.json").read_text(encoding="utf-8"))
    settings.update(anonymous_operator=True, allowed_origins=[local_origin, public_origin],
                    database="data/demo/sessions.sqlite3")
    command = [cpolar, "start" if args.tunnel else "start-all", f"-config={config}",
               "-daemon=off", "-dashboard=off", "-log=none"]
    if args.tunnel:
        command.append(args.tunnel)

    with TemporaryDirectory(prefix="safecuff-demo-") as directory:
        backend_config = Path(directory) / "console.json"
        backend_config.write_text(json.dumps(settings), encoding="utf-8")
        backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.app:create_app", "--factory",
             "--host", "127.0.0.1", "--port", str(args.port), "--no-access-log",
             "--timeout-graceful-shutdown", "3"],
            cwd=ROOT, env={**os.environ, "SAFECUFF_CONFIG": str(backend_config)},
        )
        tunnel = None
        try:
            wait_for_health(local_origin, backend, 15)
            if backend.poll() is not None:
                raise RuntimeError("The local simulator stopped before cpolar was started")
            tunnel = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_for_health(public_origin, tunnel, 30)
            print(f"Demo available at {public_origin}/ (Ctrl+C to stop)", flush=True)
            while backend.poll() is None and tunnel.poll() is None:
                time.sleep(0.5)
            raise RuntimeError("The simulator or cpolar exited")
        except KeyboardInterrupt:
            return
        except RuntimeError as exc:
            parser.exit(1, f"{exc}\n")
        finally:
            if tunnel is not None:
                stop(tunnel)
            stop(backend)


if __name__ == "__main__":
    main()
