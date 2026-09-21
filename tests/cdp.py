"""A minimal Chrome DevTools Protocol client. Stdlib only.

Only tests/test_controller_ui_smoke.py uses this. It exists so the dashboard
can be checked in a real browser without adding a Node toolchain, a driver
package, or any dependency the controller itself does not already have.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import time
import urllib.request
from pathlib import Path

CHROME_BINARIES = (
    "google-chrome-stable", "google-chrome", "chromium", "chromium-browser",
)


def find_chrome() -> str | None:
    """The first Chrome-family binary on PATH, or None."""
    for name in CHROME_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _WS:
    """The smallest RFC 6455 client that can carry CDP traffic."""

    def __init__(self, url: str):
        rest = url[len("ws://"):]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {hostport}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            self.buf += self._recv()
        head, _, self.buf = self.buf.partition(b"\r\n\r\n")
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
        ).digest()).decode()
        if accept.encode() not in head:
            raise RuntimeError(f"websocket handshake failed: {head!r}")

    def _recv(self) -> bytes:
        chunk = self.sock.recv(65536)
        if not chunk:
            raise ConnectionError("websocket closed")
        return chunk

    def _need(self, n: int) -> bytes:
        while len(self.buf) < n:
            self.buf += self._recv()
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, payload: str) -> None:
        data = payload.encode()
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        n = len(data)
        if n < 126:
            header = struct.pack("!BB", 0x81, 0x80 | n)
        elif n < (1 << 16):
            header = struct.pack("!BBH", 0x81, 0x80 | 126, n)
        else:
            header = struct.pack("!BBQ", 0x81, 0x80 | 127, n)
        self.sock.sendall(header + mask + masked)

    def recv(self) -> str:
        while True:
            b0, b1 = struct.unpack("!BB", self._need(2))
            opcode, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._need(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._need(8))[0]
            payload = self._need(n)
            if opcode == 0x8:
                raise ConnectionError("websocket closed by peer")
            if opcode == 0x9:
                self.sock.sendall(struct.pack("!BB", 0x8A, 0x80 | len(payload))
                                  + b"\x00\x00\x00\x00" + payload)
                continue
            if opcode in (0x1, 0x2):
                return payload.decode()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class Browser:
    """A headless Chrome, driven over CDP. Use it as a context manager."""

    def __init__(self, width: int = 1400, height: int = 1000):
        self.width, self.height = width, height
        self.port = free_port()
        self.proc: subprocess.Popen | None = None
        self.ws: _WS | None = None
        self._n = 0

    def __enter__(self) -> "Browser":
        binary = find_chrome()
        if not binary:
            raise RuntimeError("no Chrome binary on PATH")
        self.profile = Path(os.environ.get("TMPDIR", "/tmp")) / f"unity-hpc-cdp-{self.port}"
        self.proc = subprocess.Popen(
            [
                binary, "--headless=new", "--no-sandbox", "--disable-gpu",
                "--hide-scrollbars", "--disable-extensions",
                "--disable-background-networking", "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={self.profile}",
                f"--remote-debugging-port={self.port}",
                f"--window-size={self.width},{self.height}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 30
        target = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/list", timeout=5
                ) as fh:
                    for row in json.loads(fh.read()):
                        if row.get("type") == "page":
                            target = row["webSocketDebuggerUrl"]
                            break
                if target:
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if not target:
            self.close()
            raise RuntimeError("Chrome did not open a page target")
        self.ws = _WS(target)
        self.call("Page.enable")
        self.call("Runtime.enable")
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        if self.ws:
            self.ws.close()
            self.ws = None
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        shutil.rmtree(getattr(self, "profile", ""), ignore_errors=True)

    def call(self, method: str, **params):
        self._n += 1
        mid = self._n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def eval(self, expression: str):
        res = self.call(
            "Runtime.evaluate",
            expression=expression, returnByValue=True, awaitPromise=True,
        )
        if res.get("exceptionDetails"):
            raise RuntimeError(res["exceptionDetails"].get("text", "eval failed"))
        return res.get("result", {}).get("value")

    def goto(self, url: str, settle: float = 4.0) -> None:
        self.call("Page.navigate", url=url)
        time.sleep(settle)
