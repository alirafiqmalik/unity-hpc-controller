from pathlib import Path

SKILL = (Path(__file__).resolve().parent.parent
         / "skills" / "recommend-hardware" / "SKILL.md").read_text()


def test_ranks_on_the_projects_own_jobs():
    # It must correlate THIS project's job-ids, not only the shared aggregate.
    assert "project_hardware_profile" in SKILL or "unity_my_jobs" in SKILL


def test_has_a_cold_start_fallback_to_shared_task_profile():
    lowered = SKILL.lower()
    assert "task_profile" in SKILL           # shared fallback still referenced
    assert "fallback" in lowered or "cold" in lowered or "too few" in lowered


def test_labels_which_source_it_used():
    lowered = SKILL.lower()
    assert "project-measured" in lowered or "your jobs" in lowered or \
           "cluster-wide" in lowered
