#!/usr/bin/env python3
"""Install MAG as a launchd user agent (starts at login, restarts on crash).

Generates ~/Library/LaunchAgents/com.ericblue.mag.plist directly from this
repo's absolute path and the MAG_API_KEY in .env, so the plist never has to be
hand-edited and the key never has to be pasted into a tracked file. The
generated plist is written with mode 600.

MAG must run as a *user* LaunchAgent, not a LaunchDaemon and not a container:
Reminders and Messages are gated by macOS TCC, which only grants access to
processes running in the user's GUI session.

Usage:
  python3 scripts/install_service.py            # install and start
  python3 scripts/install_service.py --no-start # install only
  python3 scripts/install_service.py --port 8124
  python3 scripts/install_service.py --uninstall

Equivalent Makefile targets: `make service-install-auto`, `make service-uninstall`.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

LABEL = "com.ericblue.mag"
REPO = Path(__file__).resolve().parent.parent
PLIST_DEST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

# launchd's default PATH omits Homebrew, where remindctl and imsg live.
SERVICE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def read_env(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict (no interpolation, strips inline comments)."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.split("#")[0].strip()
    return env


def build_plist(api_key: str, host: str, port: str) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(REPO / ".venv" / "bin" / "python"), "-m", "mag.main"],
        "WorkingDirectory": str(REPO),
        "EnvironmentVariables": {
            "MAG_API_KEY": api_key,
            "MAG_HOST": host,
            "MAG_PORT": port,
            "MAG_LOG_LEVEL": "INFO",
            "PYTHONPATH": str(REPO / "src"),
            "PATH": SERVICE_PATH,
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(REPO / "logs" / "mag.log"),
        "StandardErrorPath": str(REPO / "logs" / "mag.error.log"),
        "ThrottleInterval": 10,
        "ProcessType": "Interactive",
    }


def _is_registered() -> bool:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def bootout(timeout: float = 10.0) -> None:
    """Unload the job and wait for launchd to actually release it.

    `bootout` returns before the domain drops its reference, and bootstrapping
    during that window fails with "Bootstrap failed: 5: Input/output error".
    """
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"],
        capture_output=True,
        check=False,
    )
    deadline = time.monotonic() + timeout
    while _is_registered() and time.monotonic() < deadline:
        time.sleep(0.25)


def bootstrap(attempts: int = 5) -> subprocess.CompletedProcess:
    """Bootstrap the job, retrying past launchd's transient EIO."""
    result = None
    for attempt in range(attempts):
        result = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST_DEST)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result
        time.sleep(1.0 * (attempt + 1))
    return result


def uninstall() -> int:
    bootout()
    if PLIST_DEST.exists():
        PLIST_DEST.unlink()
        print(f"Removed {PLIST_DEST}")
    else:
        print("Service was not installed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Port to listen on (default: MAG_PORT in .env, else 8123)")
    parser.add_argument(
        "--host", help="Address to bind (default: MAG_HOST in .env, else 127.0.0.1)"
    )
    parser.add_argument(
        "--no-start", action="store_true", help="Install the plist but do not start"
    )
    parser.add_argument("--uninstall", action="store_true", help="Stop and remove the service")
    args = parser.parse_args()

    if args.uninstall:
        return uninstall()

    venv_python = REPO / ".venv" / "bin" / "python"
    if not venv_python.exists():
        print(f"Error: {venv_python} not found. Run 'make install' first.", file=sys.stderr)
        return 1

    env = read_env(REPO / ".env")
    api_key = env.get("MAG_API_KEY", "")
    if not api_key or api_key == "your-secret-api-key":
        print(
            "Error: MAG_API_KEY is missing or still the placeholder in .env.\n"
            "       Generate one with: make generate-api-key",
            file=sys.stderr,
        )
        return 1

    host = args.host or env.get("MAG_HOST") or "127.0.0.1"
    port = args.port or env.get("MAG_PORT") or "8123"

    (REPO / "logs").mkdir(exist_ok=True)
    PLIST_DEST.parent.mkdir(parents=True, exist_ok=True)

    # Replacing a loaded job requires unloading it first.
    bootout()
    with open(PLIST_DEST, "wb") as handle:
        plistlib.dump(build_plist(api_key, host, port), handle)
    PLIST_DEST.chmod(0o600)
    print(f"Wrote {PLIST_DEST} (mode 600)")

    if args.no_start:
        print("Not starting (--no-start). Start with: make service-start")
        return 0

    result = bootstrap()
    if result.returncode != 0:
        print(f"launchctl bootstrap failed: {result.stderr.strip()}", file=sys.stderr)
        return 1

    print(f"Service started on {host}:{port}")
    print(f"Verify with: curl http://{host}:{port}/health")
    return 0


if __name__ == "__main__":
    sys.exit(main())
