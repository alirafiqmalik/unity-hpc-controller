#!/usr/bin/env python3
"""Serve the Unity HPC controller (API + dashboard). Stdlib only.

    python3 -m controller.serve
    python3 -m controller.serve --port 8300 --host 127.0.0.1
    python3 -m controller.serve --tailscale
"""

from __future__ import annotations

import argparse
import errno
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from controller.http import DEFAULT_HOST, DEFAULT_PORT, Request, handle

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


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


def _tailscale_serve(port: int) -> str | None:
    if shutil.which("tailscale") is None:
        print("tailscale not found — serving on localhost only", file=sys.stderr)
        return None
    proc = subprocess.run(
        ["tailscale", "serve", "--bg", str(port)],
        capture_output=True, text=True,
    )
    status = subprocess.run(
        ["tailscale", "serve", "status"],
        capture_output=True, text=True,
    )
    urls = [
        tok for tok in (status.stdout or "").split()
        if tok.startswith("https://")
    ]
    if proc.returncode != 0 and not urls:
        print("could not start `tailscale serve`; port is still reachable directly",
              file=sys.stderr)
        return None
    return urls[0] if urls else None


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
ExecStart={python} -m controller.serve --host 127.0.0.1 --port {port}
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
    print(f"then:         hpc-controller --tailscale   # or tailscale serve --bg {port}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="hpc-controller",
        description="Unity HPC controller — API + dashboard (Tailscale-friendly).",
    )
    ap.add_argument("--host", default=DEFAULT_HOST,
                    help=f"bind address (default {DEFAULT_HOST})")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"port (default {DEFAULT_PORT})")
    ap.add_argument("--tailscale", action="store_true",
                    help="bind localhost and publish via `tailscale serve`")
    ap.add_argument("--open", action="store_true",
                    help="open the dashboard in a local browser")
    ap.add_argument("--install-user-service", action="store_true",
                    help="write a systemd --user unit and exit")
    args = ap.parse_args(argv)

    if args.install_user_service:
        return install_user_service(args.port)

    host = "127.0.0.1" if args.tailscale else args.host
    try:
        srv = ThreadingHTTPServer((host, args.port), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(
                f"Controller cannot bind {host}:{args.port}: address already in use. "
                f"Stop the existing server or choose --port <unused-port>.",
                file=sys.stderr,
            )
            return 2
        raise

    print(f"Unity HPC controller → http://{host}:{args.port}")
    print(f"  local : http://127.0.0.1:{args.port}")
    ts_ip = _tailscale_ip()
    if ts_ip and not args.tailscale:
        print(f"  tailnet: http://{ts_ip}:{args.port}")
    ts_url = None
    if args.tailscale:
        ts_url = _tailscale_serve(args.port)
        if ts_url:
            print(f"  serve : {ts_url}")
    print("  Ctrl-C to stop.")

    if args.open:
        url = ts_url or f"http://127.0.0.1:{args.port}"
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
