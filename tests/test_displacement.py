from lib import scaffold


def test_absent_files_are_created(tmp_project):
    actions = scaffold.plan(tmp_project, "cpu")
    assert {a.kind for a in actions} == {"create"}
    report = scaffold.apply(actions)
    assert (tmp_project / "unityHPC" / "run.sh").exists()
    assert any("run.sh" in line for line in report)


def test_differing_file_is_displaced_byte_intact(tmp_project):
    unity = tmp_project / "unityHPC"
    unity.mkdir()
    handwritten = "#!/usr/bin/env bash\n# my own dispatcher\necho custom\n"
    (unity / "run.sh").write_text(handwritten)

    actions = scaffold.plan(tmp_project, "cpu")
    run_action = next(a for a in actions if a.path.name == "run.sh")
    assert run_action.kind == "replace"
    assert run_action.displaced_to == unity / ".pre-redesign" / "run.sh"

    report = scaffold.apply(actions)

    backup = unity / ".pre-redesign" / "run.sh"
    assert backup.read_text() == handwritten, "original must survive byte-intact"
    assert (unity / "run.sh").read_text() == run_action.content
    assert any(".pre-redesign/run.sh" in line for line in report), \
        "the report must name what it moved"


def test_second_run_is_idempotent_and_does_not_redisplace(tmp_project):
    scaffold.apply(scaffold.plan(tmp_project, "cpu"))
    second = scaffold.plan(tmp_project, "cpu")
    assert {a.kind for a in second} == {"skip"}
    scaffold.apply(second)
    assert not (tmp_project / "unityHPC" / ".pre-redesign").exists(), \
        "an unchanged file must never be displaced"


def test_customised_env_is_preserved_not_displaced(tmp_project):
    scaffold.apply(scaffold.plan(tmp_project, "cpu"))
    env = tmp_project / "unityHPC" / ".env"
    env.write_text('SLURM_ACCOUNT="pi_mine_umass_edu"\n')

    actions = scaffold.plan(tmp_project, "cpu")
    env_action = next(a for a in actions if a.path.name == ".env")
    assert env_action.kind == "skip", ".env is user data once it exists"
    scaffold.apply(actions)
    assert env.read_text() == 'SLURM_ACCOUNT="pi_mine_umass_edu"\n'


# ─── backups are append-only ─────────────────────────────────────────────────
#
# A field worker upgraded a project twice in a row and the second upgrade
# overwrote the first backup. For a project whose original run.sh was
# hand-written, that would have destroyed it — while the mechanism's whole
# promise is that the original is preserved.

def _handwritten(project, text):
    unity = project / "unityHPC"
    unity.mkdir(parents=True, exist_ok=True)
    (unity / "run.sh").write_text(text)
    return unity / "run.sh"


def test_a_handwritten_file_is_preserved_byte_intact(tmp_project):
    from lib import scaffold
    original = "#!/usr/bin/env bash\n# hand-written, irreplaceable\n"
    _handwritten(tmp_project, original)
    scaffold.apply(scaffold.plan(tmp_project, "cpu"))
    backup = tmp_project / "unityHPC" / scaffold.BACKUP_DIRNAME / "run.sh"
    assert backup.read_text() == original


def test_a_second_upgrade_never_overwrites_the_first_backup(tmp_project):
    """The original must survive an arbitrary number of later upgrades."""
    from lib import scaffold
    original = "#!/usr/bin/env bash\n# hand-written, irreplaceable\n"
    _handwritten(tmp_project, original)
    scaffold.apply(scaffold.plan(tmp_project, "cpu"))

    # a second, different hand-written file appears and is displaced too
    _handwritten(tmp_project, "#!/usr/bin/env bash\n# second draft\n")
    scaffold.apply(scaffold.plan(tmp_project, "cpu"))

    backup_dir = tmp_project / "unityHPC" / scaffold.BACKUP_DIRNAME
    saved = sorted(p.read_text() for p in backup_dir.glob("run.sh*"))
    assert original in saved, "the original hand-written file was lost"
    assert len(saved) == 2, f"expected both drafts kept, got {saved}"


def test_regenerating_a_generated_file_creates_no_backup_clutter(tmp_project,
                                                                 materialise):
    """A stamped file is reproducible from the plugin, so preserving copies of
    it on every upgrade would bury the one backup that matters."""
    from lib import scaffold
    materialise(tmp_project, "cpu")
    (tmp_project / "unityHPC" / "run.sh").write_text(
        'UNITY_SCAFFOLD_VERSION="0.0.1"\n# an older generated copy\n')
    report = scaffold.apply(scaffold.plan(tmp_project, "cpu"))
    backup_dir = tmp_project / "unityHPC" / scaffold.BACKUP_DIRNAME
    assert not list(backup_dir.glob("run.sh*")) if backup_dir.exists() else True
    assert any("upgraded" in line for line in report)


def test_upgrading_twice_keeps_the_handwritten_original_not_the_generated_one(
        tmp_project):
    """The exact field sequence: hand-written -> upgrade -> upgrade."""
    from lib import scaffold
    original = "#!/usr/bin/env bash\n# the user's own dispatcher\n"
    _handwritten(tmp_project, original)
    scaffold.apply(scaffold.plan(tmp_project, "cpu"))       # displaces original
    scaffold.apply(scaffold.plan(tmp_project, "gpu"))       # regenerates
    backup_dir = tmp_project / "unityHPC" / scaffold.BACKUP_DIRNAME
    assert (backup_dir / "run.sh").read_text() == original
