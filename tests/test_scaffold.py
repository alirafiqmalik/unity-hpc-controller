from pathlib import Path

import pytest

from lib import scaffold


def test_types_are_cpu_gpu_ml():
    assert scaffold.TYPES == ("cpu", "gpu", "ml")


def test_plan_cpu_creates_four_files(tmp_project):
    actions = scaffold.plan(tmp_project, "cpu")
    names = sorted(a.path.name for a in actions)
    assert names == sorted([".env", "job_template.sh", "run.sh", "sync.sh"])
    assert all(a.kind == "create" for a in actions)
    assert all(a.path.parent == tmp_project / "unityHPC" for a in actions)


def test_plan_rejects_unknown_type(tmp_project):
    try:
        scaffold.plan(tmp_project, "quantum")
    except ValueError as exc:
        assert "quantum" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown type")


def test_cpu_job_template_has_no_gpu_or_ml_tokens():
    body = (scaffold.template_root() / "cpu" / "job_template.sh").read_text()
    lowered = body.lower()
    for banned in ("cuda", "torchrun", "nvidia-smi"):
        assert banned not in lowered, f"cpu template must not mention {banned}"


def test_shipped_templates_have_no_personal_defaults():
    for path in scaffold.template_root().rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text().lower()
        for banned in ("autoresearch", "pi_taqi_umass_edu", "ahmalik"):
            assert banned not in text, f"{path.name} must not hardcode {banned}"


def test_generated_files_carry_provenance_header(tmp_project):
    for action in scaffold.plan(tmp_project, "cpu"):
        if action.path.name == ".env":
            continue
        head = "\n".join(action.content.splitlines()[:3])
        assert "/unity-hpc:setup" in head, f"{action.path.name} lacks provenance"


@pytest.mark.parametrize("ptype", ["cpu", "gpu", "ml"])
def test_plan_renders_all_four_files_for_every_type(tmp_project, ptype):
    actions = scaffold.plan(tmp_project, ptype)
    assert sorted(a.path.name for a in actions) == sorted(
        [".env", "job_template.sh", "run.sh", "sync.sh"]
    )
    assert all(a.content.strip() for a in actions)


def test_gpu_template_requests_a_gpu_but_does_not_use_torchrun():
    body = (scaffold.template_root() / "gpu" / "job_template.sh").read_text()
    assert "nvidia-smi" in body
    assert "torchrun" not in body


def test_ml_template_uses_torchrun_for_multinode():
    body = (scaffold.template_root() / "ml" / "job_template.sh").read_text()
    assert "torchrun" in body


def test_env_defaults_differ_by_type():
    def env_of(ptype):
        return (scaffold.template_root() / ptype / "env.example").read_text()

    assert 'SLURM_GPUS=""' in env_of("cpu")
    assert 'WALLTIME="04:00:00"' in env_of("cpu")
    assert 'SLURM_GPUS="1"' in env_of("gpu")
    assert 'SLURM_GPUS="1"' in env_of("ml")
    # the old universal ML default must not survive anywhere
    for ptype in scaffold.TYPES:
        assert 'WALLTIME="00:15:00"' not in env_of(ptype)


def test_generated_run_sh_is_stamped_with_the_plugin_version(tmp_project, materialise):
    """The stamp is the only way a project can learn its dispatcher is old."""
    from lib import scaffold
    unity_dir = materialise(tmp_project, "cpu")
    text = (unity_dir / "run.sh").read_text()
    assert f'UNITY_SCAFFOLD_VERSION="{scaffold.plugin_version()}"' in text
    assert scaffold.VERSION_PLACEHOLDER not in text, "placeholder left unrendered"


def test_no_scaffold_file_ships_an_unrendered_placeholder(tmp_project, materialise):
    from lib import scaffold
    unity_dir = materialise(tmp_project, "gpu")
    for name in scaffold.SCAFFOLD_FILES:
        assert scaffold.VERSION_PLACEHOLDER not in (unity_dir / name).read_text()


def test_run_sh_can_report_its_own_version(tmp_project, materialise):
    import subprocess
    from lib import scaffold
    unity_dir = materialise(tmp_project, "cpu")
    result = subprocess.run(["bash", str(unity_dir / "run.sh"), "version"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert scaffold.plugin_version() in result.stdout
