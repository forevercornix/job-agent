"""Testai deduplicator.py logikai."""

import json
import os
import tempfile

from deduplicator import deduplicate, load_seen_urls, save_seen_urls


def test_deduplicate_removes_internal_duplicates():
    jobs = [
        {"url": "https://example.com/1", "title": "A"},
        {"url": "https://example.com/1", "title": "A (duplicate)"},
        {"url": "https://example.com/2", "title": "B"},
    ]
    result = deduplicate(jobs, seen_urls=set())
    assert len(result) == 2
    assert {j["url"] for j in result} == {"https://example.com/1", "https://example.com/2"}


def test_deduplicate_removes_previously_seen():
    jobs = [
        {"url": "https://example.com/1", "title": "A"},
        {"url": "https://example.com/2", "title": "B"},
    ]
    seen = {"https://example.com/1"}
    result = deduplicate(jobs, seen_urls=seen)
    assert len(result) == 1
    assert result[0]["url"] == "https://example.com/2"


def test_deduplicate_skips_jobs_without_url():
    jobs = [{"title": "Be URL"}, {"url": "https://example.com/1", "title": "A"}]
    result = deduplicate(jobs, seen_urls=set())
    assert len(result) == 1


def test_deduplicate_empty_input():
    assert deduplicate([], seen_urls=set()) == []


def test_deduplicate_preserves_order():
    jobs = [
        {"url": "https://example.com/3", "title": "C"},
        {"url": "https://example.com/1", "title": "A"},
        {"url": "https://example.com/2", "title": "B"},
    ]
    result = deduplicate(jobs, seen_urls=set())
    assert [j["url"] for j in result] == [
        "https://example.com/3",
        "https://example.com/1",
        "https://example.com/2",
    ]


def test_save_and_load_seen_urls_roundtrip():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "seen_jobs.json")
        urls = {"https://example.com/1", "https://example.com/2"}

        save_seen_urls(path, urls)
        loaded = load_seen_urls(path)

        assert loaded == urls


def test_load_seen_urls_missing_file_returns_empty_set():
    result = load_seen_urls("/tmp/definitely_does_not_exist_12345.json")
    assert result == set()


def test_save_seen_urls_writes_valid_json():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "seen_jobs.json")
        save_seen_urls(path, {"https://example.com/1"})

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == ["https://example.com/1"]
