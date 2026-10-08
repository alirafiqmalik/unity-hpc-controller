"""hpc-controller CLI — background + Tailscale by default, stop/status, unit."""

import errno
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from controller import serve
from lib import paths


def test_tailscale_url_matches_the_controller_proxy(monkeypatch):
    status = {
        "Web": {
            "box.tailnet.ts.net:10000": {
                "Handlers": {"/": {"Proxy": "http://127.0.0.1:6080"}},
            },
            "box.tailnet.ts.net:443": {
                "Handlers": {"/": {"Proxy": "http://127.0.0.1:8300"}},
            },
        },
    }
    monkeypatch.setattr(serve.shutil, "which", lambda _name: "/usr/bin/tailscale")
    monkeypatch.setattr(serve.subprocess, "run", lambda *_a, **_k: (
        type("P", (), {"returncode": 0, "stdout": json.dumps(status)})()
    ))
    assert serve._tailscale_https_url(8300) == "https://box.tailnet.ts.net"


def test_help_documents_background_tailscale_default():
    script = Path(__file__).resolve().parent.parent / "scripts" / "hpc-controller"
    result = subprocess.run(
        ["bash", str(script), "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout + result.stderr
    assert "--tailscale" in out
    assert "--no-tailscale" in out
    assert "--fg" in out
    assert "--stop" in out
    assert "--status" in out
    assert "--port" in out
    assert "8300" in out
    assert "background" in out.lower()


def test_in_use_port(tmp_data_dir, monkeypatch, capsys):
    def occupied(*_args, **_kwargs):
        raise OSError(errno.EADDRINUSE, "address already in use")

    monkeypatch.setattr(serve, "ThreadingHTTPServer", occupied)
    assert serve.main(["--fg", "--no-tailscale", "--port", "8301"]) == 2
    err = capsys.readouterr().err
    assert "8301" in err and "already in use" in err


def test_fg_binds_localhost_and_publishes_tailscale_on_request(tmp_data_dir, monkeypatch, capsys):
    bound = {}

    class FakeSrv:
        def __init__(self, addr, _handler):
            bound["addr"] = addr

        def serve_forever(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(serve, "ThreadingHTTPServer", FakeSrv)
    monkeypatch.setattr(
        serve, "_tailscale_serve", lambda port: "https://box.tailnet.ts.net/"
    )
    assert serve.main(["--fg", "--tailscale", "--port", "8300"]) == 0
    assert bound["addr"] == ("127.0.0.1", 8300)
    out = capsys.readouterr().out
    assert "https://box.tailnet.ts.net/" in out


def test_no_tailscale_skips_serve(tmp_data_dir, monkeypatch, capsys):
    calls = []

    class FakeSrv:
        def __init__(self, addr, _handler):
            pass

        def serve_forever(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(serve, "ThreadingHTTPServer", FakeSrv)
    monkeypatch.setattr(serve, "_tailscale_serve", lambda port: calls.append(port))
    monkeypatch.setattr(
        serve, "_tailscale_https_url", lambda *_a: "https://should-not-print.ts.net"
    )
    monkeypatch.setattr(serve, "_tailscale_ip", lambda: None)
    assert serve.main(["--fg", "--no-tailscale", "--port", "8300"]) == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "https://should-not-print.ts.net" not in out
    assert "serve :" not in out


def test_background_start_passes_tailscale_through(tmp_data_dir, monkeypatch, capsys):
    class FakeProc:
        pid = 4242

        def poll(self):
            return None

    spawned = {}
    real_popen = subprocess.Popen

    def fake_popen(cmd, **kwargs):
        if isinstance(cmd, list) and "controller.serve" in cmd:
            spawned["cmd"] = cmd
            spawned["kwargs"] = kwargs
            return FakeProc()
        return real_popen(cmd, **kwargs)

    monkeypatch.setattr(serve.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(serve, "_wait_healthy", lambda **_k: True)
    monkeypatch.setattr(
        serve, "_tailscale_https_url", lambda *_a: "https://box.tailnet.ts.net/"
    )
    monkeypatch.setattr(serve, "_tailscale_ip", lambda: None)
    assert serve.main(["--tailscale", "--port", "8300"]) == 0
    assert "--fg" in spawned["cmd"] and "--tailscale" in spawned["cmd"]
    assert spawned["kwargs"].get("start_new_session") is True
    runtime = json.loads(paths.controller_runtime().read_text())
    assert runtime["pid"] == 4242
    assert runtime["port"] == 8300
    out = capsys.readouterr().out
    assert "https://box.tailnet.ts.net/" in out
    assert "4242" in out


def test_already_running_is_idempotent(tmp_data_dir, monkeypatch, capsys):
    paths.controller_dir().mkdir(parents=True, exist_ok=True)
    paths.controller_runtime().write_text(json.dumps({
        "pid": 7, "port": 8300, "host": "127.0.0.1",
    }))
    monkeypatch.setattr(serve, "_pid_alive", lambda pid: pid == 7)
    monkeypatch.setattr(serve, "_health_ok", lambda **_k: True)
    monkeypatch.setattr(
        serve, "_tailscale_https_url", lambda *_a: "https://box.tailnet.ts.net/"
    )

    def boom(*_a, **_k):
        raise AssertionError("should not spawn a second controller")

    monkeypatch.setattr(serve, "_spawn_background", boom)
    monkeypatch.setattr(serve, "ThreadingHTTPServer", boom)
    monkeypatch.setattr(serve, "_tailscale_ip", lambda: None)
    assert serve.main([]) == 0
    out = capsys.readouterr().out
    assert "already" in out.lower()
    assert "https://box.tailnet.ts.net/" in out


def test_stop_ends_a_background_controller(tmp_data_dir):
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    paths.controller_dir().mkdir(parents=True, exist_ok=True)
    paths.controller_runtime().write_text(json.dumps({
        "pid": proc.pid, "port": 8300, "host": "127.0.0.1",
    }))
    try:
        assert serve.main(["--stop"]) == 0
        proc.wait(timeout=3)
        assert proc.poll() is not None
        assert not paths.controller_runtime().exists()
    finally:
        if proc.poll() is None:
            os.kill(proc.pid, signal.SIGKILL)
            proc.wait(timeout=2)


def test_status_when_not_running(tmp_data_dir, capsys):
    assert serve.main(["--status"]) == 0
    out = capsys.readouterr().out.lower()
    assert "not running" in out


def test_install_user_service_is_foreground_and_tailscale_ready(
    tmp_path, monkeypatch, capsys,
):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert serve.main(["--install-user-service", "--port", "8310"]) == 0
    unit = tmp_path / ".config" / "systemd" / "user" / "unity-hpc-controller.service"
    text = unit.read_text()
    assert "8310" in text
    assert "controller.serve" in text
    assert "--fg" in text
    out = capsys.readouterr().out
    assert "enable --now" in out
    assert "hpc-controller --tailscale" not in out


def test_isolated_service_preserves_backend_paths_and_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    data = tmp_path / "backend data%"
    monkeypatch.setenv("UNITY_HPC_DATA", str(data))
    assert serve.main(["--install-user-service", "--service-name", "unity-refinement",
                       "--port", "8301", "--host", "127.0.0.2", "--no-tailscale"]) == 0
    units = tmp_path / ".config" / "systemd" / "user"
    assert not (units / "unity-hpc-controller.service").exists()
    text = (units / "unity-refinement.service").read_text()
    assert 'Environment="UNITY_HPC_DATA=' + str(data).replace("%", "%%") + '"' in text
    assert '"127.0.0.2"' in text and '"8301"' in text
    assert '"--tailscale"' not in text
    assert "--legacy-projects" not in text and "--no-build-ui" not in text
    assert "Restart=on-failure" in text and "CPUSchedulingPolicy=other" in text


def test_service_installer_rejects_path_as_unit_name(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(SystemExit) as error:
        serve.main(["--install-user-service", "--service-name", "../other"])
    assert error.value.code == 2
    assert not (tmp_path / ".config" / "systemd" / "other.service").exists()
