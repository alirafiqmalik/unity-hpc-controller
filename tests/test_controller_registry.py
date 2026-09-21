"""Controller project registry — attach, list, update, detach."""

from pathlib import Path

import pytest

from controller import registry
from controller.registry import RegistryError


def test_attach_round_trip(tmp_project, tmp_data_dir):
    rec = registry.attach("phd-gnn", tmp_project, primitive="gpu")
    assert rec["slug"] == "phd-gnn"
    assert rec["path"] == str(tmp_project.resolve())
    assert rec["primitive"] == "gpu"
    listed = registry.list_projects()
    assert len(listed) == 1
    assert listed[0]["slug"] == "phd-gnn"
    assert registry.get("phd-gnn")["path"] == rec["path"]


def test_attach_rejects_bad_slug(tmp_project, tmp_data_dir):
    with pytest.raises(RegistryError, match="invalid slug"):
        registry.attach("../etc", tmp_project)
    with pytest.raises(RegistryError, match="invalid slug"):
        registry.attach("Has Spaces", tmp_project)


def test_attach_rejects_unknown_primitive(tmp_project, tmp_data_dir):
    with pytest.raises(RegistryError, match="unknown primitive"):
        registry.attach("proj", tmp_project, primitive="quantum")


def test_attach_rejects_missing_directory(tmp_data_dir, tmp_path):
    with pytest.raises(RegistryError, match="not a directory"):
        registry.attach("proj", tmp_path / "nope")


def test_update_and_detach(tmp_project, tmp_data_dir):
    registry.attach("alpha", tmp_project, primitive="cpu")
    updated = registry.update("alpha", campaign="sweep-1", remote_dir="/work/a")
    assert updated["campaign"] == "sweep-1"
    assert updated["remote_dir"] == "/work/a"
    assert registry.detach("alpha") is True
    assert registry.get("alpha") is None
    assert registry.detach("alpha") is False


def test_attach_is_idempotent_on_slug(tmp_project, tmp_data_dir):
    first = registry.attach("alpha", tmp_project, primitive="cpu")
    second = registry.attach("alpha", tmp_project, primitive="gpu")
    assert first["attached_utc"] == second["attached_utc"]
    assert second["primitive"] == "gpu"
    assert len(registry.list_projects()) == 1


def test_corrupt_registry_degrades_to_empty(tmp_project, tmp_data_dir):
    from lib import paths
    paths.projects_registry().parent.mkdir(parents=True, exist_ok=True)
    paths.projects_registry().write_text("{not json")
    assert registry.list_projects() == []
    registry.attach("ok", tmp_project)
    assert registry.get("ok") is not None
