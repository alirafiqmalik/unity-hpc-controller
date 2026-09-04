import os
import subprocess

import pytest

PTYPES = ["cpu", "gpu", "ml"]


def _render_with(unity_dir, env, exp="baseline"):
    """Render, with REMOTE_DIR pinned to the real project dir so the rendered
    job body's relative `unityHPC/bootstrap.sh` check and its flock lock file
    land somewhere that actually exists on disk."""
    full = dict(os.environ)
    full.update(env)
    result = subprocess.run(
        ["bash", str(unity_dir / "run.sh"), "render", exp],
        capture_output=True, text=True, env=full,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _run_job(unity_dir, tmp_project, job_command="true", exp="baseline", extra_env=None):
    """Render then actually execute the job body locally, the way the node
    would, with REMOTE_DIR == the real project checkout."""
    env = {"REMOTE_DIR": str(tmp_project), "JOB_COMMAND": job_command}
    if extra_env:
        env.update(extra_env)
    script = _render_with(unity_dir, env, exp=exp)
    full = dict(os.environ)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=full,
                          cwd=str(tmp_project))


@pytest.mark.parametrize("ptype", PTYPES)
def test_absent_hook_keeps_todays_activate_or_run_path(tmp_project, materialise, ptype):
    """No unityHPC/bootstrap.sh: behaviour matches today, venv activation and
    all, and no lock file is created."""
    unity_dir = materialise(tmp_project, ptype)
    venv = tmp_project / "fakevenv" / "bin"
    venv.mkdir(parents=True)
    (venv / "activate").write_text("export MARKER=activated\n")

    result = _run_job(unity_dir, tmp_project, job_command="printf %s \"$MARKER\"",
                      extra_env={"VENV_PATH": str(tmp_project / "fakevenv")})
    assert result.returncode == 0, result.stderr
    assert "activated" in result.stdout
    assert not (tmp_project / ".unity_bootstrap.lock").exists()


@pytest.mark.parametrize("ptype", PTYPES)
def test_present_hook_is_sourced_once_under_the_lock(tmp_project, materialise, ptype):
    """The hook runs, its exports reach the job command, and a lock file is
    used to guard it."""
    unity_dir = materialise(tmp_project, ptype)
    counter = tmp_project / "count.txt"
    (unity_dir / "bootstrap.sh").write_text(
        f'echo x >> "{counter}"\nexport MARKER=from-hook\n'
    )

    result = _run_job(unity_dir, tmp_project, job_command="printf %s \"$MARKER\"")
    assert result.returncode == 0, result.stderr
    assert "from-hook" in result.stdout
    assert counter.read_text().count("x") == 1
    assert (tmp_project / ".unity_bootstrap.lock").exists()


@pytest.mark.parametrize("ptype", PTYPES)
def test_a_second_concurrent_task_waits_then_skips(tmp_project, materialise, ptype):
    """Two tasks starting together must not both run the hook's guarded body
    at once: the lock serialises them, and a hook written the way the
    original workaround was (skip if already done) does its real work once."""
    unity_dir = materialise(tmp_project, ptype)
    marker = tmp_project / "done.marker"
    log = tmp_project / "order.log"
    (unity_dir / "bootstrap.sh").write_text(f'''
if [ -f "{marker}" ]; then
    echo skip >> "{log}"
    return 0
fi
echo start >> "{log}"
sleep 0.5
touch "{marker}"
echo end >> "{log}"
''')

    procs = [
        subprocess.Popen(
            ["bash", "-c", _render_with(unity_dir, {"REMOTE_DIR": str(tmp_project),
                                                     "JOB_COMMAND": "true"})],
            cwd=str(tmp_project), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        for _ in range(2)
    ]
    results = [(p.wait(), p.communicate()) for p in [procs[0]] + [procs[1]]]
    for rc, (_out, err) in results:
        assert rc == 0, err

    lines = log.read_text().splitlines()
    # one task does the real work (start ... end back to back, uninterrupted
    # by the other), the other only ever sees "skip" -- proof the lock
    # serialised them rather than letting both race the sleep at once.
    assert lines.count("start") == 1
    assert lines.count("end") == 1
    assert lines.count("skip") == 1
    start_i, end_i = lines.index("start"), lines.index("end")
    assert end_i == start_i + 1, f"a second task interleaved with the critical section: {lines}"


@pytest.mark.parametrize("ptype", PTYPES)
def test_set_e_does_not_abort_the_exists_path(tmp_project, materialise, ptype):
    """A present hook must not be skipped or the job aborted by the classic
    `set -e` / `[ ... ] && ...` trap: the job command still runs to
    completion and its own exit code is what comes back."""
    unity_dir = materialise(tmp_project, ptype)
    (unity_dir / "bootstrap.sh").write_text("export MARKER=ok\n")

    result = _run_job(unity_dir, tmp_project,
                      job_command="printf %s \"$MARKER\"; sh -c 'exit 7'")
    assert result.returncode == 7, result.stderr
    assert "ok" in result.stdout
    assert "=== done" in result.stdout
