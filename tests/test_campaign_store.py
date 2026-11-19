"""Campaign journal transactions, schema setup, and concurrent access."""

import json
import sqlite3
import threading

import pytest

from controller import campaigns, campaign_contract, campaign_lifecycle as lifecycle, campaign_store as store
from controller.campaign_contract import Conflict
from controller.http import Request, handle


def _db(data):
    return data / "controller/campaigns.db"


def _one_campaign():
    store.accept("study", {"campaign_id": "study", "tasks": [{"task_id": "a"}]},
                 "hash-1", [], {"task_count": 1})


def _copy(source, target_dir):
    target = _db(target_dir)
    target.parent.mkdir(parents=True)
    original = sqlite3.connect(source)
    copied = sqlite3.connect(target)
    try:
        original.backup(copied)
    finally:
        copied.close()
        original.close()
    return target


def test_schema_one_journal_migrates_as_before(tmp_data_dir, tmp_path, monkeypatch):
    _one_campaign()
    store.record_intent("study", "a", lifecycle.intent(1, "job-1"))
    receipt = {"outcome": "accepted", "job_id": "123"}
    store.record_submission("study", "a", 1, receipt, lifecycle.submitted(receipt))
    store.record_transition("study", "a", "fetching", job_id="123", observation={
        "job_id": "123", "state": "COMPLETED", "exit_code": "0:0", "fetch_attempts": 0,
    })
    store.record_transition("study", "a", "completed", artifacts={"files": [], "complete": True}, error=None)
    legacy = tmp_path / "legacy"
    copied = _copy(_db(tmp_data_dir), legacy)
    connection = sqlite3.connect(copied)
    try:
        with connection:
            connection.execute("UPDATE attempts SET state='fetching'")
            connection.execute("ALTER TABLE attempts DROP COLUMN observation")
            connection.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    finally:
        connection.close()
    monkeypatch.setenv("UNITY_HPC_DATA", str(legacy))
    migrated = store.read("study")
    assert migrated["attempts"][0]["state"] == "completed"
    assert migrated["attempts"][0]["observation"] == migrated["tasks"][0]["observation"]
    assert migrated["attempts"][0]["receipt"] == receipt
    assert migrated["tasks"][0]["artifacts"]["complete"]
    connection = sqlite3.connect(copied)
    try:
        assert connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"
    finally:
        connection.close()


def _traced(monkeypatch):
    statements = []
    original = store._connect

    def connect(path):
        connection = original(path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(store, "_connect", connect)
    return statements


def _start(operation):
    values, errors = [], []

    def run():
        try:
            values.append(operation())
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, values, errors


def _joined(work):
    thread, values, errors = work
    thread.join(5)
    assert not thread.is_alive()
    assert not errors, errors
    return values[0]


@pytest.fixture
def accepting(tmp_data_dir, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "run.py").write_text("print('scientific task')\n")
    campaigns.configure({"account": "pi_test", "remote_root": "/work/pi_test/controller"})

    def declaration(campaign_id, memory_mb=81151):
        return {
            "schema_version": 1, "campaign_id": campaign_id, "bundle": {"path": str(source)},
            "max_concurrent": 2, "max_attempts": 2,
            "tasks": [{"task_id": "model-a", "model_class": "small-a10080-v1",
                       "argv": ["python3", "run.py", "{output_dir}"], "env": {},
                       "resources": {"gpu_type": "a100", "gpu_count": 1, "cpus": 4,
                                     "memory_mb": 32768, "walltime_seconds": 3600,
                                     "constraint": "a100-80g&sapphirerapids",
                                     "expected_gpu_name": "NVIDIA A100-SXM4-80GB",
                                     "expected_gpu_memory_mb": memory_mb},
                       "outputs": ["results.jsonl", "summary.json"]}],
        }

    return declaration


def test_read_does_not_wait_for_a_held_write_lock(tmp_data_dir):
    _one_campaign()
    connection = sqlite3.connect(_db(tmp_data_dir), isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE campaigns SET error='uncommitted'")

        def reads():
            return (store.read("study"), store.listing(), store.results("study"),
                    store.identities_excluding({"completed"}), store.tasks_in_states({"waiting"}),
                    store.prior_acceptance("study", []))

        campaign, listing, results, identities, tasks, prior = _joined(_start(reads))
        assert campaign["error"] is None
        assert listing[0]["error"] is None
        assert results["events"][0]["kind"] == "accepted"
        assert identities == ["study"]
        assert tasks[0]["task_id"] == "a"
        assert prior == ("hash-1", {})
    finally:
        connection.execute("ROLLBACK")
        connection.close()


def test_long_listing_does_not_fail_concurrent_reads_or_writes(tmp_data_dir, monkeypatch):
    _one_campaign()
    started, release = threading.Event(), threading.Event()
    decode_lock = threading.Lock()
    original = store._decode

    def decode(row):
        with decode_lock:
            first = not started.is_set()
            if first:
                started.set()
        if first:
            assert release.wait(10)
        return original(row)

    monkeypatch.setattr(store, "_decode", decode)
    listing = _start(store.listing)
    try:
        assert started.wait(5)

        def concurrent_operations():
            before = store.read("study")
            store.record_transition("study", "a", "waiting", error="probe")
            store.record_campaign_error("study", "reconcile", "probe")
            return before, store.read("study")

        before, after = _joined(_start(concurrent_operations))
        assert before["error"] is None
        assert after["error"] == "reconcile: probe"
        assert after["tasks"][0]["error"] == "probe"
    finally:
        release.set()
        listing[0].join(5)
    assert _joined(listing)[0]["error"] is None


def test_listings_are_serialized_to_limit_peak_memory(tmp_data_dir, monkeypatch):
    _one_campaign()
    first_decoding, second_started, second_decoding, release = (
        threading.Event() for _ in range(4)
    )
    decode_lock = threading.Lock()
    original = store._decode

    def decode(row):
        with decode_lock:
            first = not first_decoding.is_set()
            if first:
                first_decoding.set()
            else:
                second_decoding.set()
        if first:
            assert release.wait(10)
        return original(row)

    def second_listing():
        second_started.set()
        return store.listing()

    monkeypatch.setattr(store, "_decode", decode)
    first = _start(store.listing)
    second = None
    try:
        assert first_decoding.wait(5)
        second = _start(second_listing)
        assert second_started.wait(5)
        assert not second_decoding.wait(0.2)
        assert second[0].is_alive()
    finally:
        release.set()
        first[0].join(5)
        if second is not None:
            second[0].join(5)
    assert _joined(first) == _joined(second)
    assert second_decoding.is_set()


def test_schema_setup_runs_once_per_process_and_path(tmp_data_dir, tmp_path, monkeypatch):
    statements = _traced(monkeypatch)
    assert store.listing() == []
    assert statements.count("PRAGMA journal_mode=WAL") == 1
    assert any(sql.lstrip().startswith("CREATE TABLE IF NOT EXISTS meta") for sql in statements)

    statements.clear()
    _one_campaign()
    store.read("study")
    store.listing()
    store.record_transition("study", "a", "waiting", error="x")
    store.roll_up("study")
    assert not any(word in sql.lower() for sql in statements
                   for word in ("journal_mode", "create table", "schema_version", "table_info"))

    statements.clear()
    monkeypatch.setenv("UNITY_HPC_DATA", str(tmp_path / "second"))
    assert store.listing() == []
    assert statements.count("PRAGMA journal_mode=WAL") == 1
    assert sum(sql.lstrip().startswith("CREATE TABLE IF NOT EXISTS meta") for sql in statements) == 1

    statements.clear()
    monkeypatch.setenv("UNITY_HPC_DATA", str(tmp_path / "third"))
    barrier = threading.Barrier(8)

    def listing():
        barrier.wait(5)
        return store.listing()

    work = [_start(listing) for _ in range(8)]
    assert [_joined(item) for item in work] == [[]] * 8
    assert statements.count("PRAGMA journal_mode=WAL") == 1


def test_current_schema_opens_without_migration_or_rewrite(tmp_data_dir, tmp_path, monkeypatch):
    _one_campaign()
    copied = _copy(_db(tmp_data_dir), tmp_path / "copy")
    monkeypatch.setenv("UNITY_HPC_DATA", str(tmp_path / "copy"))
    before = copied.read_bytes()
    statements = _traced(monkeypatch)
    assert store.read("study")["id"] == "study"
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "ALTER", "DELETE"))
                   for sql in statements)
    assert copied.read_bytes() == before


def test_new_data_directory_gets_the_current_schema(tmp_path, monkeypatch):
    fresh = tmp_path / "fresh"
    monkeypatch.setenv("UNITY_HPC_DATA", str(fresh))
    assert not fresh.exists()
    assert store.listing() == []
    assert _db(fresh).is_file()
    connection = sqlite3.connect(_db(fresh))
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"
        assert "observation" in {row[1] for row in connection.execute("PRAGMA table_info(attempts)")}
    finally:
        connection.close()
    with pytest.raises(FileNotFoundError, match="unknown campaign: missing"):
        store.read("missing")


def test_unsupported_schema_version_is_refused_on_every_use(tmp_path, monkeypatch):
    future = tmp_path / "future"
    _db(future).parent.mkdir(parents=True)
    connection = sqlite3.connect(_db(future))
    try:
        with connection:
            connection.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)")
            connection.execute("INSERT INTO meta VALUES('schema_version','3')")
        monkeypatch.setenv("UNITY_HPC_DATA", str(future))
        for _ in range(2):
            with pytest.raises(Conflict, match="unsupported campaigns database schema"):
                store.listing()
        assert handle(Request("GET", "/api/v1/campaigns")).status == 409
        assert connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "3"
    finally:
        connection.close()


def test_submission_outcome_and_receipt_commit_together(tmp_data_dir):
    _one_campaign()
    store.record_intent("study", "a", lifecycle.intent(1, "job-1"))
    cursor = store.results("study")["next_cursor"]
    receipt = {"outcome": "accepted", "job_id": "7"}
    step = lifecycle.submitted(receipt)
    with pytest.raises(TypeError):
        store.record_submission("study", "a", 1, {**receipt, "bad": object()}, step)
    campaign = store.read("study")
    assert campaign["tasks"][0]["state"] == "submitting"
    assert campaign["attempts"][0]["state"] == "submitting"
    assert campaign["attempts"][0]["receipt"] is None
    assert store.results("study", after=cursor)["events"] == []

    store.record_submission("study", "a", 1, receipt, step)
    campaign = store.read("study")
    assert campaign["tasks"][0]["state"] == "accepted"
    assert campaign["attempts"][0]["state"] == "accepted"
    assert campaign["attempts"][0]["receipt"] == receipt
    assert [event["kind"] for event in store.results("study", after=cursor)["events"]] == ["accepted"]


def test_intent_publishes_attempt_and_job_name_with_its_attempt_row(tmp_data_dir, monkeypatch):
    _one_campaign()
    cursor = store.results("study")["next_cursor"]

    def refused(*args):
        raise sqlite3.OperationalError("event write refused")

    with monkeypatch.context() as patch:
        patch.setattr(store, "_event", refused)
        with pytest.raises(sqlite3.OperationalError):
            store.record_intent("study", "a", lifecycle.intent(1, "job-1"))
    campaign = store.read("study")
    assert (campaign["tasks"][0]["state"], campaign["tasks"][0]["attempt"], campaign["attempts"]) == ("waiting", 0, [])

    store.record_intent("study", "a", lifecycle.intent(1, "job-1"))
    response = handle(Request("GET", "/api/v1/campaigns/study/results", {"after": [str(cursor)]}))
    assert response.status == 200
    events = json.loads(response.body)["events"]
    assert [(e["task_id"], e["kind"], e["payload"]) for e in events] == [
        ("a", "submitting", {"attempt": 1, "job_name": "job-1"})]
    campaign = store.read("study")
    assert (campaign["tasks"][0]["state"], campaign["tasks"][0]["attempt"], campaign["tasks"][0]["job_name"]) == (
        "submitting", 1, "job-1")
    assert [(a["attempt"], a["job_name"], a["state"]) for a in campaign["attempts"]] == [(1, "job-1", "submitting")]


def test_replayed_observations_publish_only_state_and_queue_changes(tmp_data_dir):
    _one_campaign()
    store.record_intent("study", "a", lifecycle.intent(1, "job-1"))
    receipt = {"outcome": "accepted", "job_id": "123"}
    store.record_submission("study", "a", 1, receipt, lifecycle.submitted(receipt))
    polls = [("PENDING", "Priority"), ("PENDING", "Priority"), ("PENDING", "Resources"), ("PENDING", "Resources"),
             ("PENDING", "Priority"), ("RUNNING", None), ("RUNNING", None)]
    published = []
    for elapsed, (state, reason) in enumerate(polls):
        task = store.read("study")["tasks"][0]
        raw = {"job_id": "123", "state": state, "pending_reason": reason, "elapsed_seconds": elapsed}
        step = lifecycle.observed(task, raw, cancelling=False, max_attempts=2, now=0).step
        cursor = store.results("study")["next_cursor"]
        store.record_transition("study", "a", step.state, **step.fields)
        published.append([(e["kind"], e["payload"]) for e in store.results("study", after=cursor)["events"]])
    assert [len(events) for events in published] == [1, 0, 1, 0, 1, 1, 0]
    assert published[2] == [("accepted", {"job_id": "123", "error": None, "observation": {
        "job_id": "123", "state": "PENDING", "pending_reason": "Resources", "elapsed_seconds": 2, "fetch_attempts": 0}})]
    assert published[5] == [("running", {"job_id": "123", "error": None, "observation": {
        "job_id": "123", "state": "RUNNING", "pending_reason": None, "elapsed_seconds": 5, "fetch_attempts": 0}})]
    assert store.read("study")["tasks"][0]["observation"]["elapsed_seconds"] == 6


def test_acceptance_compresses_without_holding_the_write_lock(accepting, tmp_data_dir, monkeypatch):
    original = campaign_contract.snapshot
    probes = []

    def snapshot(*args, **kwargs):
        connection = sqlite3.connect(_db(tmp_data_dir), timeout=0.1, isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("ROLLBACK")
            probes.append(True)
        finally:
            connection.close()
        return original(*args, **kwargs)

    monkeypatch.setattr(campaign_contract, "snapshot", snapshot)
    assert campaigns.create(accepting("study"))["id"] == "study"
    assert probes == [True]


def test_concurrent_identical_acceptance_records_one_campaign(accepting):
    barrier = threading.Barrier(2)

    def accept():
        barrier.wait(5)
        return campaigns.create(accepting("study"))

    work = [_start(accept) for _ in range(2)]
    assert sorted(_joined(item)["idempotent"] for item in work) == [False, True]
    assert len(store.listing()) == 1
    assert sum(event["task_id"] is None and event["kind"] == "accepted"
               for event in store.results("study")["events"]) == 1


def test_concurrent_conflicting_hardware_acceptance_admits_one(accepting, tmp_data_dir):
    barrier = threading.Barrier(2)

    def accept(identity, memory_mb):
        barrier.wait(5)
        return campaigns.create(accepting(identity, memory_mb=memory_mb))

    work = [_start(lambda: accept("first", 81151)), _start(lambda: accept("second", 40960))]
    for thread, _, _ in work:
        thread.join(5)
        assert not thread.is_alive()
    values = [value for _, results, _ in work for value in results]
    errors = [error for _, _, exceptions in work for error in exceptions]
    assert len(values) == len(errors) == 1
    assert isinstance(errors[0], Conflict)
    assert "locked to different hardware" in str(errors[0])
    assert len(store.listing()) == 1
    connection = sqlite3.connect(_db(tmp_data_dir))
    try:
        assert connection.execute("SELECT COUNT(*) FROM hardware_locks").fetchone()[0] == 1
    finally:
        connection.close()


def test_campaign_error_belongs_to_one_worker_step(tmp_data_dir):
    _one_campaign()
    cursor = store.results("study")["next_cursor"]
    assert store.record_campaign_error("study", "stage", "rsync failed") is True
    assert store.record_campaign_error("study", "stage", "rsync failed") is False
    assert store.read("study")["error"] == "stage: rsync failed"
    assert store.error_step("stage: rsync failed") == "stage"
    assert store.error_step("scheduler observation failed: x") == "reconcile"
    assert store.error_step(None) is None
    store.clear_campaign_error("study", "reconcile: other")
    assert store.read("study")["error"] == "stage: rsync failed"
    store.clear_campaign_error("study", "stage: rsync failed")
    assert store.read("study")["error"] is None
    store.record_campaign_error("study", "placement", "x")
    store.record_staged("study", {})
    campaign = store.read("study")
    assert campaign["staged"] == 1
    assert campaign["error"] == "placement: x"
    with pytest.raises(ValueError):
        store.record_campaign_error("study", "observe", "x")
    with pytest.raises(FileNotFoundError):
        store.record_campaign_error("missing", "stage", "x")
    assert [event["kind"] for event in store.results("study", after=cursor)["events"]] == ["source_staged"]


def test_staging_commit_resolves_only_a_stage_error(tmp_data_dir):
    _one_campaign()
    store.record_campaign_error("study", "stage", "rsync failed")
    store.record_staged("study", {})
    staged = store.read("study")
    assert staged["staged"] == 1 and staged["error"] is None
    store.record_campaign_error("study", "placement", "no catalog")
    store.record_staged("study", {})
    assert store.read("study")["error"] == "placement: no catalog"


def test_intent_with_an_unknown_state_is_refused_and_writes_nothing(tmp_data_dir):
    _one_campaign()
    cursor = store.results("study")["next_cursor"]
    valid = lifecycle.intent(1, "job-1")
    with pytest.raises(ValueError):
        store.record_intent("study", "a", lifecycle.Step("not-a-task-state", valid.fields))
    campaign = store.read("study")
    assert campaign["tasks"][0]["state"] == "waiting"
    assert campaign["tasks"][0]["attempt"] == 0
    assert campaign["attempts"] == []
    assert store.results("study", after=cursor)["events"] == []
