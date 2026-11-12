"""Large accounting inputs must not exhaust the controller service's memory."""

import json
import subprocess
import sys
from pathlib import Path


def test_large_accounting_day_under_memory_limit(tmp_path):
    source = tmp_path / "2026-01-01"
    source.mkdir()
    record = {
        "job_id": "123",
        "state": "COMPLETED",
        "exit_code": 0,
        "elapsed_s": 1,
        "padding": "x" * 65536,
    }
    line = json.dumps(record) + "\n"
    with (source / "task_runs.jsonl").open("w") as stream:
        for _ in range(1024):
            stream.write(line)
    root = Path(__file__).resolve().parents[1]
    program = """
import resource, sqlite3, sys
from pathlib import Path
resource.setrlimit(resource.RLIMIT_AS, (128 * 1024**2, 128 * 1024**2))
sys.path.insert(0, str(Path(sys.argv[1]) / 'cluster-intel'))
import rollup
connection = sqlite3.connect(':memory:')
connection.create_function('is_terminal', 1, lambda state: int(state == 'COMPLETED'))
connection.executescript(rollup.SCHEMA)
rollup._process_day(connection, '2026-01-01', Path(sys.argv[2]))
assert connection.execute('SELECT COUNT(*) FROM task_run').fetchone()[0] == 1
assert connection.execute('SELECT state FROM task_run').fetchone()[0] == 'COMPLETED'
assert connection.execute('SELECT fully_summarised FROM day_index').fetchone()[0] == 1
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(root), str(source)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
