"""Testai circuit_breaker.py logikai - grynosios funkcijos, be I/O (išskyrus load/save)."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import circuit_breaker as cb


def test_new_source_defaults_to_closed():
    state = {}
    assert cb.should_attempt(state, "NewSource") is True


def test_single_failure_keeps_closed():
    state = {}
    state = cb.record_result(state, "SourceA", success=False)

    assert state["SourceA"]["status"] == cb.CLOSED
    assert state["SourceA"]["consecutive_failures"] == 1
    assert cb.should_attempt(state, "SourceA") is True


def test_reaching_threshold_opens_circuit():
    state = {}
    now = datetime.now(timezone.utc)
    for _ in range(cb.FAILURE_THRESHOLD):
        state = cb.record_result(state, "SourceA", success=False, now=now)

    assert state["SourceA"]["status"] == cb.OPEN
    assert cb.should_attempt(state, "SourceA", now=now) is False


def test_open_circuit_blocks_until_cooldown_passes():
    state = {}
    now = datetime.now(timezone.utc)
    for _ in range(cb.FAILURE_THRESHOLD):
        state = cb.record_result(state, "SourceA", success=False, now=now)

    just_before_cooldown = now + timedelta(hours=cb.COOLDOWN_HOURS - 1)
    assert cb.should_attempt(state, "SourceA", now=just_before_cooldown) is False

    just_after_cooldown = now + timedelta(hours=cb.COOLDOWN_HOURS + 1)
    assert cb.should_attempt(state, "SourceA", now=just_after_cooldown) is True


def test_success_after_open_closes_circuit():
    state = {}
    now = datetime.now(timezone.utc)
    for _ in range(cb.FAILURE_THRESHOLD):
        state = cb.record_result(state, "SourceA", success=False, now=now)
    assert state["SourceA"]["status"] == cb.OPEN

    later = now + timedelta(hours=cb.COOLDOWN_HOURS + 1)
    state = cb.record_result(state, "SourceA", success=True, now=later)

    assert state["SourceA"]["status"] == cb.CLOSED
    assert state["SourceA"]["consecutive_failures"] == 0
    assert cb.should_attempt(state, "SourceA", now=later) is True


def test_success_resets_consecutive_failures_before_threshold():
    """1 nesėkmė, tada sėkmė - skaitliukas turi nulintis, o ne kauptis toliau."""
    state = {}
    state = cb.record_result(state, "SourceA", success=False)
    state = cb.record_result(state, "SourceA", success=False)
    state = cb.record_result(state, "SourceA", success=True)

    assert state["SourceA"]["consecutive_failures"] == 0
    assert state["SourceA"]["status"] == cb.CLOSED


def test_sources_are_tracked_independently():
    state = {}
    now = datetime.now(timezone.utc)
    for _ in range(cb.FAILURE_THRESHOLD):
        state = cb.record_result(state, "BadSource", success=False, now=now)
    state = cb.record_result(state, "GoodSource", success=True, now=now)

    assert cb.should_attempt(state, "BadSource", now=now) is False
    assert cb.should_attempt(state, "GoodSource", now=now) is True


def test_save_and_load_state_roundtrip():
    state = {}
    state = cb.record_result(state, "SourceA", success=False)

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "cb_state.json")
        cb.save_state(state, path)
        loaded = cb.load_state(path)

    assert loaded["SourceA"]["consecutive_failures"] == 1


def test_load_state_missing_file_returns_empty_dict():
    result = cb.load_state("/tmp/definitely_does_not_exist_cb_98765.json")
    assert result == {}


def test_save_state_writes_valid_json():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "cb_state.json")
        state = {}
        state = cb.record_result(state, "SourceA", success=False)
        cb.save_state(state, path)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

    assert "SourceA" in data
    assert data["SourceA"]["status"] == cb.CLOSED
