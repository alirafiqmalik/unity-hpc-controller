from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCHED = ("skills", "agents", "templates", "scripts", "mcp")


def _text_files():
    for top in SEARCHED:
        for path in (REPO_ROOT / top).rglob("*"):
            if path.is_file() and path.suffix in {".md", ".sh", ".py", ""} \
                    and "__pycache__" not in path.parts:
                yield path


def test_old_root_templates_are_gone():
    assert not (REPO_ROOT / "templates" / "job_template.sh").exists()
    assert not (REPO_ROOT / "templates" / ".env.example").exists()


def test_nothing_references_the_retired_templates():
    offenders = []
    for path in _text_files():
        text = path.read_text(errors="replace")
        if "templates/job_template.sh" in text or "templates/.env.example" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"stale template references in: {offenders}"


def test_no_unresolvable_plugin_dir_anywhere():
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in _text_files()
        if "<plugin_dir>" in p.read_text(errors="replace")
    ]
    assert not offenders, f"<plugin_dir> still present in: {offenders}"
