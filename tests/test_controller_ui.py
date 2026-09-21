from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "controller" / "ui" / "index.html"


def test_controller_ui_is_a_live_dashboard():
    html = UI.read_text()
    assert "/api/v1/projects" in html
    assert "uhpc_sk_agent" not in html
    assert "X-Token" not in html
    assert "v2.0-mock" not in html
    assert "Design mock" not in html
    assert "fetch('/api/v1/projects" in html
    for primitive in ("cpu", "gpu", "ml", "multi-cpu", "multi-gpu"):
        assert primitive in html
    assert "openProject" in html
