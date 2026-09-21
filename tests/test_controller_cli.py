"""hpc-controller CLI — help, bind failure, install-user-service."""

import errno
import sys
from pathlib import Path

from controller import serve


def test_help_mentions_tailscale():
    import subprocess
    script = Path(__file__).resolve().parent.parent / "scripts" / "hpc-controller"
    result = subprocess.run(
        ["bash", str(script), "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout + result.stderr
    assert "--tailscale" in out
    assert "--port" in out
    assert "8300" in out


def test_in_use_port(tmp_data_dir, monkeypatch, capsys):
    def occupied(*_args, **_kwargs):
        raise OSError(errno.EADDRINUSE, "address already in use")

    monkeypatch.setattr(serve, "ThreadingHTTPServer", occupied)
    assert serve.main(["--port", "8301"]) == 2
    err = capsys.readouterr().err
    assert "8301" in err and "already in use" in err


def test_install_user_service(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert serve.main(["--install-user-service", "--port", "8310"]) == 0
    unit = tmp_path / ".config" / "systemd" / "user" / "unity-hpc-controller.service"
    text = unit.read_text()
    assert "8310" in text
    assert "controller.serve" in text
    assert "enable --now" in capsys.readouterr().out
