from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "skills"


def test_only_three_skill_dirs_exist():
    dirs = sorted(p.name for p in SKILLS.iterdir() if p.is_dir())
    assert dirs == ["connect", "dispatch", "doctor"]


def test_each_skill_has_skill_md():
    for name in ("connect", "dispatch", "doctor"):
        assert (SKILLS / name / "SKILL.md").is_file()


def test_connect_mentions_projects_api():
    text = (SKILLS / "connect" / "SKILL.md").read_text()
    assert "/api/v1/projects" in text


def test_dispatch_mentions_project_runs_api():
    text = (SKILLS / "dispatch" / "SKILL.md").read_text()
    assert "/api/v1/projects/" in text
    assert "/runs" in text


def test_doctor_mentions_health_api():
    text = (SKILLS / "doctor" / "SKILL.md").read_text()
    assert "/api/v1/health" in text
