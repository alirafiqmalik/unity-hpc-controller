#!/usr/bin/env python3
"""Serve the Unity HPC controller (API + dashboard). Stdlib only.

    hpc-controller                 # background + Tailscale HTTPS (default)
    hpc-controller --status
    hpc-controller --stop
    hpc-controller --fg            # stay in the terminal
    hpc-controller --no-tailscale  # localhost only
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from controller import telemetry
from controller.http import DEFAULT_HOST, DEFAULT_PORT, Request, UI_DIR, WEB_DIR, handle
from lib import paths

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

#: How long one `npm` step may take before the start-up gives up on it.
BUILD_TIMEOUT_S = 900


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _dispatch(self, method: str) -> None:
        req = Request(
            method=method,
            path=self.path.split("?", 1)[0],
            query=parse_qs(self.path.split("?", 1)[1] if "?" in self.path else ""),
            body=self._read_body() if method in ("POST", "PATCH", "PUT") else b"",
        )
        resp = handle(req)
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.body)))
        # `no-store` is the default, and it is right for every API answer and
        # for index.html. A response that sets its own Cache-Control keeps it:
        # sending both puts two headers on the wire, and a client combines them
        # into one list where `no-store` wins, so a hashed asset would never be
        # cached. Only the route knows which of the two it needs.
        if "Cache-Control" not in resp.headers:
            self.send_header("Cache-Control", "no-store")
        for key, value in resp.headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(resp.body)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")



def dashboard_built() -> bool:
    """True when `controller/web/dist` holds a built page."""
    return (UI_DIR / "index.html").is_file()


def _npm() -> str | None:
    return shutil.which("npm")


def _run_npm(args: list[str], note: str) -> bool:
    """Run one npm step in `controller/web`, streaming its output."""
    npm = _npm()
    if npm is None:
        return False
    print(f"  {note} ...", flush=True)
    try:
        proc = subprocess.run(
            [npm, *args],
            cwd=WEB_DIR,
            timeout=BUILD_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(f"  {note}: timed out after {BUILD_TIMEOUT_S}s", file=sys.stderr)
        return False
    except OSError as exc:
        print(f"  {note}: {exc}", file=sys.stderr)
        return False
    return proc.returncode == 0


def ensure_dashboard(force: bool = False) -> bool:
    """
    Build the dashboard when it is missing.

    The controller ships the dashboard as source, so the first start on a
    machine builds it. A later start finds `dist/` and does nothing, which
    keeps start-up instant. `force` rebuilds an existing `dist/`.

    A failure here never stops the controller: the API is the part that must
    come up, and `http._static` answers 503 with the two commands to run.
    ADR 0006.
    """
    if not WEB_DIR.is_dir():
        return False
    if dashboard_built() and not force:
        return True
    if _npm() is None:
        print(
            "The dashboard is not built and npm is not on PATH.\n"
            "  Install Node 20 or newer, then run:\n"
            "    cd controller/web && npm install && npm run build\n"
            "  The API is up; the dashboard page answers 503 until then.",
            file=sys.stderr,
        )
        return False

    print("Building the dashboard (first start on this machine).")
    if not (WEB_DIR / "node_modules").is_dir():
        if not _run_npm(["install", "--no-audit", "--no-fund"], "npm install"):
            print("  npm install failed; the dashboard stays unbuilt.", file=sys.stderr)
            return False
    if not _run_npm(["run", "build"], "npm run build"):
        print("  npm run build failed; the dashboard stays unbuilt.", file=sys.stderr)
        return False
    print("  dashboard built.")
    return True


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_runtime() -> dict | None:
    path = paths.controller_runtime()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "pid" not in data:
        return None
    return data


def _write_runtime(pid: int, host: str, port: int) -> None:
    dest = paths.controller_runtime()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"pid": pid, "host": host, "port": port}) + "\n")


def _clear_runtime() -> None:
    try:
        paths.controller_runtime().unlink()
    except OSError:
        pass


def _health_ok(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> bool:
    del host  # health is always the loopback API, even when bind is 0.0.0.0
    url = f"http://127.0.0.1:{port}/api/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=0.4) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read().decode())
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return False
    return body.get("ok") is True and body.get("service") == "unity-hpc-controller"


def _wait_healthy(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                  timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _health_ok(host=host, port=port):
            return True
        time.sleep(0.1)
    return False


def _tailscale_https_url(port: int = DEFAULT_PORT) -> str | None:
    if shutil.which("tailscale") is None:
        return None
    try:
        status = subprocess.run(
            ["tailscale", "serve", "status", "--json"],
            capture_output=True, text=True, timeout=5,
        )
        if status.returncode != 0:
            return None
        web = json.loads(status.stdout).get("Web", {})
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        return None
    for authority, site in web.items():
        proxy = site.get("Handlers", {}).get("/", {}).get("Proxy", "")
        target = urlsplit(proxy)
        if target.hostname not in ("127.0.0.1", "localhost") or target.port != port:
            continue
        url = urlsplit("https://" + authority)
        return f"https://{url.hostname}" + (f":{url.port}" if url.port != 443 else "")
    return None


def _tailscale_serve(port: int) -> str | None:
    if shutil.which("tailscale") is None:
        print("tailscale not found — serving on localhost only", file=sys.stderr)
        return None
    proc = subprocess.run(
        ["tailscale", "serve", "--bg", str(port)],
        capture_output=True, text=True,
    )
    url = _tailscale_https_url(port)
    if proc.returncode != 0 and not url:
        print("could not start `tailscale serve`; port is still reachable directly",
              file=sys.stderr)
        return None
    return url


def _tailscale_ip() -> str | None:
    if shutil.which("tailscale") is None:
        return None
    proc = subprocess.run(
        ["tailscale", "ip", "-4"], capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    line = (proc.stdout or "").strip().splitlines()
    return line[0] if line else None


def _print_urls(host: str, port: int, ts_url: str | None = None,
                pid: int | None = None) -> None:
    print(f"Unity HPC controller → http://{host}:{port}")
    print(f"  local : http://127.0.0.1:{port}")
    if pid is not None:
        print(f"  pid   : {pid}")
    ts_ip = _tailscale_ip()
    if ts_ip:
        print(f"  tailnet: http://{ts_ip}:{port}")
    if ts_url:
        print(f"  serve : {ts_url}")
    log = paths.controller_log()
    if log.exists():
        print(f"  log   : {log}")


def _open_browser(url: str) -> None:
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def _controller_running(port: int) -> tuple[bool, dict | None]:
    runtime = _read_runtime()
    if runtime is None:
        return False, None
    try:
        pid = int(runtime["pid"])
        rt_port = int(runtime.get("port", port))
    except (TypeError, ValueError):
        return False, runtime
    alive = _pid_alive(pid)
    healthy = _health_ok(port=rt_port)
    if alive or healthy:
        return True, runtime
    return False, runtime


def _spawn_background(host: str, port: int, tailscale: bool) -> subprocess.Popen:
    log = paths.controller_log()
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "controller.serve",
        "--fg", "--host", host, "--port", str(port),
    ]
    if not tailscale:
        cmd.append("--no-tailscale")
    env = os.environ.copy()
    extra = str(REPO)
    env["PYTHONPATH"] = extra + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    with log.open("a") as fh:
        return subprocess.Popen(
            cmd,
            stdout=fh,
            stderr=fh,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(REPO),
            env=env,
        )


def _stop() -> int:
    runtime = _read_runtime()
    if runtime is None:
        print("controller is not running")
        return 0
    try:
        pid = int(runtime["pid"])
    except (TypeError, ValueError):
        _clear_runtime()
        print("controller is not running")
        return 0
    if not _pid_alive(pid):
        _clear_runtime()
        print("controller is not running")
        return 0
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            break
        time.sleep(0.05)
    _clear_runtime()
    print(f"stopped pid {pid}")
    return 0


def _status() -> int:
    runtime = _read_runtime()
    port = DEFAULT_PORT
    host = DEFAULT_HOST
    if runtime:
        try:
            port = int(runtime.get("port", port))
            host = str(runtime.get("host") or host)
        except (TypeError, ValueError):
            pass
    running, rt = _controller_running(port)
    if not running:
        print("controller is not running")
        return 0
    pid = None
    if rt:
        try:
            pid = int(rt["pid"])
        except (TypeError, ValueError, KeyError):
            pid = None
    print("controller is running")
    _print_urls(host, port, ts_url=_tailscale_https_url(port), pid=pid)
    return 0


def install_user_service(port: int) -> int:
    """Write a systemd --user unit that keeps the controller up."""
    dest_dir = Path.home() / ".config" / "systemd" / "user"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "unity-hpc-controller.service"
    python = sys.executable
    unit = f"""[Unit]
Description=Unity HPC controller (dashboard + API)
After=network.target

[Service]
Type=simple
ExecStart={python} -m controller.serve --fg --port {port}
WorkingDirectory={REPO}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
    dest.write_text(unit)
    print(f"wrote {dest}")
    print("enable with:  systemctl --user daemon-reload")
    print("              systemctl --user enable --now unity-hpc-controller")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="hpc-controller",
        description=(
            "Unity HPC controller — API + dashboard. "
            "Starts in the background and publishes over Tailscale by default."
        ),
        epilog="Do not use `tailscale funnel` — that publishes the dashboard to the internet.",
    )
    ap.add_argument("--host", default=DEFAULT_HOST,
                    help=f"bind address (default {DEFAULT_HOST})")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"port (default {DEFAULT_PORT})")
    ap.add_argument(
        "--tailscale",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="publish via `tailscale serve` (default: on)",
    )
    ap.add_argument("--fg", "--foreground", action="store_true",
                    help="stay in the foreground (default is background)")
    ap.add_argument("--stop", action="store_true",
                    help="stop the background controller")
    ap.add_argument("--status", action="store_true",
                    help="print whether the controller is running, and its URLs")
    ap.add_argument("--open", action="store_true",
                    help="open the dashboard in a local browser")
    ap.add_argument("--install-user-service", action="store_true",
                    help="write a systemd --user unit and exit")
    ap.add_argument("--build-ui", action="store_true",
                    help="rebuild the dashboard even when controller/web/dist exists")
    ap.add_argument("--no-build-ui", action="store_true",
                    help="never build the dashboard on start")
    args = ap.parse_args(argv)

    if args.install_user_service:
        return install_user_service(args.port)
    if args.stop:
        return _stop()
    if args.status:
        return _status()

    # The dashboard is built from source on the first start of a machine, so
    # a fresh clone serves a page without a separate step. ADR 0006.
    if not args.no_build_ui:
        ensure_dashboard(force=args.build_ui)

    host = args.host
    port = args.port
    running, runtime = _controller_running(port)
    if running and not args.fg:
        print("already running")
        rt_host = host
        rt_port = port
        pid = None
        if runtime:
            rt_host = str(runtime.get("host") or host)
            try:
                rt_port = int(runtime.get("port", port))
                pid = int(runtime["pid"])
            except (TypeError, ValueError, KeyError):
                pid = runtime.get("pid") if runtime else None
        ts_url = _tailscale_https_url(rt_port)
        _print_urls(rt_host, rt_port, ts_url=ts_url, pid=pid)
        if args.open:
            _open_browser(ts_url or f"http://127.0.0.1:{rt_port}")
        return 0

    if not args.fg:
        if runtime and not running:
            _clear_runtime()
        proc = _spawn_background(host, port, args.tailscale)
        _write_runtime(proc.pid, host, port)
        if proc.poll() is not None:
            print(
                f"failed to start the controller; see {paths.controller_log()}",
                file=sys.stderr,
            )
            _clear_runtime()
            return 1
        if not _wait_healthy(host=host, port=port):
            print(
                f"controller started (pid {proc.pid}) but is not healthy yet; "
                f"see {paths.controller_log()}",
                file=sys.stderr,
            )
            return 1
        ts_url = _tailscale_https_url(port) if args.tailscale else None
        _print_urls(host, port, ts_url=ts_url, pid=proc.pid)
        print("  stop  : hpc-controller --stop")
        if args.open:
            _open_browser(ts_url or f"http://127.0.0.1:{port}")
        return 0

    try:
        srv = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(
                f"Controller cannot bind {host}:{port}: address already in use. "
                f"Stop the existing server or choose --port <unused-port>.",
                file=sys.stderr,
            )
            return 2
        raise

    _write_runtime(os.getpid(), host, port)
    # The schedule sleeps in this process until a run is due. It does nothing
    # until an operator switches it on. ADR 0004.
    telemetry.start_scheduler()
    from controller import workspace_worker
    workspace_worker.start()
    ts_url = _tailscale_serve(port) if args.tailscale else None
    _print_urls(host, port, ts_url=ts_url, pid=os.getpid())
    print("  Ctrl-C to stop.")

    if args.open:
        _open_browser(ts_url or f"http://127.0.0.1:{port}")

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        workspace_worker.stop()
        telemetry.stop_scheduler()
        _clear_runtime()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
