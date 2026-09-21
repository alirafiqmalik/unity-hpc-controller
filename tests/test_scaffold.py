import os
import subprocess
from pathlib import Path

import pytest

from lib import scaffold


def test_types_are_the_five_primitives():
    assert scaffold.TYPES == ("cpu", "gpu", "ml", "multi-cpu", "multi-gpu")


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
        assert "/unity-hpc:connect" in head, f"{action.path.name} lacks provenance"


# parametrized over TYPES itself, not a copy of it: a name added to TYPES with
# no template directory behind it must fail here rather than at a user's sbatch.
@pytest.mark.parametrize("ptype", scaffold.TYPES)
def test_plan_renders_all_four_files_for_every_type(tmp_project, ptype):
    actions = scaffold.plan(tmp_project, ptype)
    assert sorted(a.path.name for a in actions) == sorted(
        [".env", "job_template.sh", "run.sh", "sync.sh"]
    )
    assert all(a.content.strip() for a in actions)


@pytest.mark.parametrize("ptype,resource", [("multi-cpu", "cpu"), ("multi-gpu", "gpu")])
def test_a_fan_out_type_renders_its_resource_template(tmp_project, ptype, resource):
    """multi-cpu and multi-gpu are orchestration on the cpu and gpu resources, so
    every file they render is the resource type's file, byte for byte (spec §9)."""
    assert ({a.path.name: a.content for a in scaffold.plan(tmp_project, ptype)}
            == {a.path.name: a.content for a in scaffold.plan(tmp_project, resource)})


def test_no_multi_star_template_directory_exists():
    """Spec §9: the fan-out names reuse cpu/ and gpu/. A multi-*/ directory would
    be a second copy of a job template, free to drift from the one it forked."""
    assert not list(scaffold.template_root().glob("multi-*"))


def test_gpu_template_requests_a_gpu_but_does_not_use_torchrun():
    body = (scaffold.template_root() / "gpu" / "job_template.sh").read_text()
    assert "nvidia-smi" in body


def test_gpu_and_ml_templates_have_opt_in_sampling():
    for ptype in ("gpu", "ml"):
        body = (scaffold.template_root() / ptype / "job_template.sh").read_text()
        assert "GPU_SAMPLE_INTERVAL" in body
        assert "memory.used" in body
        assert "GPU_SAMPLE_FILE" in body


def test_the_sample_file_extension_matches_what_it_writes():
    """The sampler writes a comma-separated header and comma-separated rows into
    a file named .tsv, so anything reading it by extension parsed one column."""
    for ptype in ("gpu", "ml"):
        body = (scaffold.template_root() / ptype / "job_template.sh").read_text()
        assert ".gpu.csv" in body, ptype
        assert ".gpu.tsv" not in body, ptype
        assert "timestamp_utc,gpu_index" in body, ptype


@pytest.mark.parametrize("ptype", ["gpu", "ml"])
def test_the_banner_survives_a_node_without_a_gpu(ptype, tmp_path):
    """nvidia-smi writes "No devices were found" to STDOUT and exits non-zero.
    Under `set -o pipefail` the old one-liner emitted that text AND its own
    fallback, so a real run printed `gpu=No devices were found\\nunknown ===`
    and split the banner across two lines."""
    body = (scaffold.template_root() / ptype / "job_template.sh").read_text()
    start = body.index("GPU_NAME=")
    snippet = body[start:body.index("echo \"===", start)]

    stub = tmp_path / "nvidia-smi"
    stub.write_text("#!/usr/bin/env bash\necho 'No devices were found'\nexit 9\n")
    stub.chmod(0o755)
    script = tmp_path / "probe.sh"
    script.write_text("set -euo pipefail\n" + snippet + '\nprintf "gpu=%s|\\n" "$GPU_NAME"\n')

    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "gpu=unknown|\n", result.stdout


def test_cpu_template_has_no_gpu_sampling():
    body = (scaffold.template_root() / "cpu" / "job_template.sh").read_text()
    assert "GPU_SAMPLE_INTERVAL" not in body
    assert "torchrun" not in body


def test_ml_template_uses_torchrun_for_multinode():
    body = (scaffold.template_root() / "ml" / "job_template.sh").read_text()
    assert "torchrun" in body


def test_env_defaults_differ_by_type():
    def env_of(resource_dir):
        return (scaffold.template_root() / resource_dir / "env.example").read_text()

    assert 'SLURM_GPUS=""' in env_of("cpu")
    assert 'WALLTIME="04:00:00"' in env_of("cpu")
    assert 'SLURM_GPUS="1"' in env_of("gpu")
    assert 'SLURM_GPUS="1"' in env_of("ml")
    # the old universal ML default must not survive in any template. Walks the
    # resource directories rather than TYPES: multi-cpu and multi-gpu have no
    # directory of their own (spec §9), they resolve to cpu/ and gpu/.
    for resource_dir in sorted(set(scaffold._RESOURCE_DIR.values())):
        assert 'WALLTIME="00:15:00"' not in env_of(resource_dir)


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
