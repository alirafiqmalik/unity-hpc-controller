"""Reject malformed requests before scheduling and bound large dependency graphs."""

import pytest

from controller.campaign_contract import CampaignError, inventory, validate


def declaration(tmp_path):
    (tmp_path / "run.py").write_text("print('task')\n")
    return {"schema_version": 1, "campaign_id": "validation", "bundle": {"path": str(tmp_path)},
            "tasks": [{"task_id": "task", "argv": ["python3", "run.py"], "outputs": ["result.json"]}]}


@pytest.mark.parametrize("field,value", [("qos", True), ("qos", 42), ("nodelist", ["cpu001"]),
                                         ("expected_gpu_uuid", {"uuid": "GPU-abc"})])
def test_malformed_optional_resources_fail_before_submission(tmp_path, field, value):
    request = declaration(tmp_path)
    request["tasks"][0]["resources"] = {field: value}
    with pytest.raises(CampaignError, match=field):
        validate(request)


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_schema_version_requires_an_integer(tmp_path, version):
    request = declaration(tmp_path)
    request["schema_version"] = version
    with pytest.raises(CampaignError, match="schema_version"):
        validate(request)


def test_normalized_directory_output_and_empty_bundle_are_rejected(tmp_path):
    request = declaration(tmp_path)
    request["tasks"][0]["outputs"] = ["./"]
    with pytest.raises(CampaignError, match="output"):
        validate(request)
    request["bundle"]["path"] = ""
    with pytest.raises(CampaignError, match="bundle.path"):
        validate(request)


def test_long_dependency_chain_and_cycles_do_not_exhaust_python_stack(tmp_path):
    request = declaration(tmp_path)
    request["tasks"] = [{"task_id": f"task-{index}", "argv": ["python3", "run.py"],
                         "outputs": ["result.json"], "depends_on": [f"task-{index-1}"] if index else []}
                        for index in range(1200)]
    assert len(validate(request)["tasks"]) == 1200
    request["tasks"][0]["depends_on"] = ["task-1199"]
    with pytest.raises(CampaignError, match="cycle"):
        validate(request)


def test_common_local_credentials_never_enter_bundle(tmp_path):
    request = declaration(tmp_path)
    (tmp_path / ".env.local").write_text("example secret")
    (tmp_path / "id_ed25519").write_text("example private key")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh/config").write_text("example connection")
    frozen = inventory(validate(request)["bundle"])
    assert [entry["path"] for entry in frozen["files"]] == ["run.py"]
