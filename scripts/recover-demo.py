"""Restore the console and existing reserved cpolar tunnel; never print/read its config."""
import os
from pathlib import Path
import subprocess
import urllib.request

home = Path.home()
test = home / ".local/state/safecuff-web-test-20261116"
binary = home / ".local/opt/cpolar/cpolar"
config = test / "cpolar.yml"
pidfile = test / "cpolar.pid"
subprocess.run(["systemctl", "--user", "start", "safecuff-console.service"], check=True)
running = []
for proc in Path("/proc").iterdir():
    if not proc.name.isdigit():
        continue
    try:
        if (proc / "exe").resolve(strict=True) == binary.resolve() and proc.stat().st_uid == os.getuid():
            running.append(int(proc.name))
    except (FileNotFoundError, PermissionError):
        pass
if running:
    print("Existing cpolar retained; no parallel tunnel started.")
else:
    assert config.is_file() and config.stat().st_mode & 0o077 == 0, "Private tunnel config missing or permissions unsafe"
    process = subprocess.Popen([str(binary), "start-all", "-config=" + str(config), "-daemon=off", "-dashboard=off", "-log=none"],
        cwd=test, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    pidfile.write_text(str(process.pid))
    os.chmod(pidfile, 0o600)
    print("Started cpolar using existing reserved-domain configuration.")
try:
    with urllib.request.urlopen("https://safetyring.cpolar.cn/healthz", timeout=15) as response:
        print("Fixed HTTPS health:", response.status)
except Exception:
    print("HTTPS not ready yet; retry the fixed health URL shortly.")
