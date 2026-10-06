"""Viewer partitions, typed columns and selections share one local record source."""

import pytest

from controller.genai_datasets import select_records, viewer_metadata


def test_partitions_preserve_real_file_split_and_subset():
    records = [
        {"inputs": {"question": "one"}, "tags": {"subsets": "comparison"}, "source": {"path": "dataset/x/meta-test.jsonl"}},
        {"inputs": {"question": "two"}, "tags": {"subsets": "superlative"}, "source": {"path": "dataset/x/meta-test.jsonl"}},
    ]
    viewer = viewer_metadata(records, {}, "comparison", "meta-test")
    assert viewer["rows"] == 1 and viewer["total_rows"] == 2
    assert viewer["splits"] == [{"name": "meta-test", "rows": 1}]
    assert select_records(records, {}, "comparison", "meta-test") == records[:1]
    with pytest.raises(ValueError, match="Unknown dataset split"):
        select_records(records, {}, split="train")
    with pytest.raises(ValueError, match="Unknown dataset subset"):
        select_records(records, {}, subset="invented")


def test_unpartitioned_corpus_has_no_invented_training_split():
    viewer = viewer_metadata([{"inputs": {"problem": "x"}, "source": {"path": "puzzles/X.md"}}], {})
    assert viewer["subsets"][0]["name"] == "default"
    assert viewer["splits"] == [{"name": "local", "rows": 1}]
    assert viewer["kind"] == "Code / formal specification"


def test_chat_and_preference_columns_retain_nested_types_and_missing_counts():
    records = [
        {"inputs": {"messages": [{"role": "user", "content": "hello"}], "chosen": "good", "rejected": "bad"}, "expectations": {"score": 2}},
        {"inputs": {"messages": [{"role": "assistant", "content": "hi"}], "chosen": "fine", "rejected": "poor"}},
    ]
    viewer = viewer_metadata(records, {})
    columns = {column["key"]: column for column in viewer["columns"]}
    assert viewer["kind"] == "Preference pairs"
    assert columns["inputs.messages"]["type"] == "messages"
    assert columns["expectations.score"]["stats"]["missing"] == 1
    assert sum(columns["inputs.chosen"]["stats"]["histogram"]) == 2


def test_explicit_split_takes_precedence_over_source_filename():
    records = [{"inputs": {"value": True}, "source": {"path": "train.jsonl", "split": "validation", "config": "en"}}]
    viewer = viewer_metadata(records, {})
    assert viewer["subsets"][0]["name"] == "en"
    assert viewer["splits"] == [{"name": "validation", "rows": 1}]
