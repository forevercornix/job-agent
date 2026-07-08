"""
Testai manifest.py - RunManifest statuso nustatymo logikai. Tai svarbiausia
dalis testuoti, nes ji atsakinga už tikslų atskyrimą "agentas nepasileido"
nuo "agentas pasileido ir tiesiog nieko naujo nerado".
"""

import json
import os
import tempfile

from manifest import (
    STATUS_ALL_API_CALLS_FAILED,
    STATUS_ALL_SOURCES_CIRCUIT_OPEN,
    STATUS_ALL_SOURCES_FAILED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_NO_SOURCES_CONFIGURED,
    STATUS_OK,
    STATUS_OK_NO_NEW_JOBS,
    STATUS_PREFLIGHT_FAILED,
    RunManifest,
)


def _make_source_stat(name, attempts, successes, jobs_found=0):
    return {
        "name": name,
        "attempts": attempts,
        "successes": successes,
        "failures": attempts - successes,
        "jobs_found": jobs_found,
    }


def test_status_preflight_failed_takes_priority():
    """Preflight klaida - svarbiausia, nepriklausomai nuo kitų būsenų."""
    m = RunManifest()
    m.set_preflight(False, "invalid API key")
    m.set_sources([{"name": "X"}])  # net jei šaltiniai sukonfigūruoti

    assert m.determine_status() == STATUS_PREFLIGHT_FAILED


def test_status_no_sources_configured():
    m = RunManifest()
    m.set_preflight(True)
    m.set_sources([])

    assert m.determine_status() == STATUS_NO_SOURCES_CONFIGURED


def test_status_all_sources_failed():
    """Visi šaltiniai sukonfigūruoti, bet nė vienas realiai neveikė - tai NĖRA 'ok_no_new_jobs'."""
    m = RunManifest()
    m.set_preflight(True)
    m.set_sources([{"name": "A"}, {"name": "B"}])
    m.set_scrape_results(0, [
        _make_source_stat("A", attempts=2, successes=0),
        _make_source_stat("B", attempts=2, successes=0),
    ])

    assert m.determine_status() == STATUS_ALL_SOURCES_FAILED


def test_status_ok_no_new_jobs_when_sources_worked_but_nothing_new():
    """Šaltiniai veikė sėkmingai, bet visi skelbimai jau anksčiau matyti - tai NORMALU."""
    m = RunManifest()
    m.set_preflight(True)
    m.set_sources([{"name": "A"}])
    m.set_scrape_results(5, [_make_source_stat("A", attempts=1, successes=1, jobs_found=5)])
    m.set_dedup_results(0)

    assert m.determine_status() == STATUS_OK_NO_NEW_JOBS


def test_status_all_api_calls_failed():
    m = RunManifest()
    m.set_preflight(True)
    m.set_sources([{"name": "A"}])
    m.set_scrape_results(3, [_make_source_stat("A", attempts=1, successes=1, jobs_found=3)])
    m.set_dedup_results(3)
    m.set_rank_results(api_calls_made=3, api_call_errors=3, jobs_matched=0)

    assert m.determine_status() == STATUS_ALL_API_CALLS_FAILED


def test_status_completed_with_errors_partial_api_failures():
    """Dalis API kvietimų nepavyko, bet ne visi - tai 'completed_with_errors', ne 'ok'."""
    m = RunManifest()
    m.set_preflight(True)
    m.set_sources([{"name": "A"}])
    m.set_scrape_results(3, [_make_source_stat("A", attempts=1, successes=1, jobs_found=3)])
    m.set_dedup_results(3)
    m.set_rank_results(api_calls_made=3, api_call_errors=1, jobs_matched=1)

    assert m.determine_status() == STATUS_COMPLETED_WITH_ERRORS


def test_status_ok_full_success():
    m = RunManifest()
    m.set_preflight(True)
    m.set_sources([{"name": "A"}])
    m.set_scrape_results(3, [_make_source_stat("A", attempts=1, successes=1, jobs_found=3)])
    m.set_dedup_results(3)
    m.set_rank_results(api_calls_made=3, api_call_errors=0, jobs_matched=2)

    assert m.determine_status() == STATUS_OK


def test_finalize_sets_finished_at_and_status():
    m = RunManifest()
    m.set_preflight(True)
    m.set_sources([{"name": "A"}])
    m.set_scrape_results(0, [_make_source_stat("A", attempts=1, successes=1, jobs_found=0)])
    m.set_dedup_results(0)

    assert m.finished_at is None
    m.finalize()
    assert m.finished_at is not None
    assert m.status == STATUS_OK_NO_NEW_JOBS


def test_save_writes_valid_json():
    m = RunManifest()
    m.set_preflight(True)
    m.set_sources([{"name": "A"}])
    m.finalize(STATUS_OK)

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "run_manifest.json")
        m.save(path)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["status"] == STATUS_OK
        assert data["preflight_ok"] is True
        assert data["sources_configured"] == 1
        assert "started_at" in data
        assert "finished_at" in data


def test_preflight_failure_adds_error_message():
    m = RunManifest()
    m.set_preflight(False, "connection timeout")

    assert len(m.errors) == 1
    assert "connection timeout" in m.errors[0]


def test_set_rank_results_tracks_ungrounded_count():
    m = RunManifest()
    m.set_rank_results(api_calls_made=5, api_call_errors=0, jobs_matched=3, ungrounded_count=2)

    assert m.ungrounded_count == 2
    assert any("nužeminti" in e for e in m.errors)


def test_ungrounded_count_appears_in_manifest_dict():
    m = RunManifest()
    m.set_rank_results(api_calls_made=5, api_call_errors=0, jobs_matched=3, ungrounded_count=2)
    m.finalize()

    data = m.to_dict()
    assert data["ungrounded_count"] == 2


def test_status_all_sources_circuit_open():
    """Jei VISI šaltiniai praleisti dėl circuit breaker, tai NĖRA 'all_sources_failed' -
    tai atskiras statusas (breaker veikia taip, kaip suprojektuota)."""
    m = RunManifest()
    m.set_preflight(True)
    m.set_sources([{"name": "A"}, {"name": "B"}])
    m.set_scrape_results(0, [
        {"name": "A", "attempts": 0, "successes": 0, "failures": 0, "jobs_found": 0, "circuit_breaker_skipped": True},
        {"name": "B", "attempts": 0, "successes": 0, "failures": 0, "jobs_found": 0, "circuit_breaker_skipped": True},
    ])

    assert m.determine_status() == STATUS_ALL_SOURCES_CIRCUIT_OPEN


def test_status_all_sources_circuit_open_not_in_critical_statuses():
    """Circuit breaker veikimas nėra kritinė klaida - exit code turi likti 0."""
    from manifest import CRITICAL_STATUSES

    assert STATUS_ALL_SOURCES_CIRCUIT_OPEN not in CRITICAL_STATUSES


def test_status_mixed_circuit_open_and_real_failure_is_all_sources_failed():
    """Jei bent vienas šaltinis realiai bandytas ir nepavyko (ne circuit-skip),
    o kitas praleistas - tai vis tiek all_sources_failed, nes NĖ VIENAS
    sėkmingai neveikė."""
    m = RunManifest()
    m.set_preflight(True)
    m.set_sources([{"name": "A"}, {"name": "B"}])
    m.set_scrape_results(0, [
        {"name": "A", "attempts": 0, "successes": 0, "failures": 0, "jobs_found": 0, "circuit_breaker_skipped": True},
        {"name": "B", "attempts": 2, "successes": 0, "failures": 2, "jobs_found": 0, "circuit_breaker_skipped": False},
    ])

    assert m.determine_status() == STATUS_ALL_SOURCES_FAILED


def test_log_summary_calls_logger_with_full_dict():
    from unittest.mock import MagicMock

    m = RunManifest()
    m.set_preflight(True)
    m.set_sources([{"name": "A"}])
    m.finalize(STATUS_OK)

    mock_logger = MagicMock()
    m.log_summary(mock_logger)

    mock_logger.info.assert_called_once()
    _, kwargs = mock_logger.info.call_args
    assert kwargs["extra"]["event"] == "run_complete"
    assert kwargs["extra"]["status"] == STATUS_OK
