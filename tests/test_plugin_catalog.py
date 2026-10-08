from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "skills"


def test_only_three_skill_dirs_exist():
    dirs = sorted(p.name for p in SKILLS.iterdir() if p.is_dir())
    assert dirs == ["connect", "dispatch", "doctor"]


def test_each_skill_has_skill_md():
    for name in ("connect", "dispatch", "doctor"):
        assert (SKILLS / name / "SKILL.md").is_file()


def test_connect_prepares_campaigns():
    text = (SKILLS / "connect" / "SKILL.md").read_text()
    assert "mcp__unity-hpc__unity_campaign_plan" in text


def test_dispatch_uses_campaign_lifecycle():
    text = (SKILLS / "dispatch" / "SKILL.md").read_text()
    assert "mcp__unity-hpc__unity_campaign_submit" in text
    assert "mcp__unity-hpc__unity_campaign_results" in text


def test_doctor_checks_headless_backend():
    text = (SKILLS / "doctor" / "SKILL.md").read_text()
    assert "mcp__unity-hpc__unity_doctor" in text
    assert "mcp__unity-hpc__unity_backend" in text
