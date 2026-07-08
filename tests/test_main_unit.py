"""
Tiesioginiai main.py orkestracijos testai (skirtingai nuo
test_main_integration.py, kuris paleidžia main.py per subprocess -
subprocess'e vykdomas kodas NEMATOMAS coverage.py įrankiui, tad šie testai
svarbūs realiam code coverage matavimui).

Visi išoriniai priklausomumai (preflight_check, load_sources, scrape_all,
deduplicate, rank_jobs, seen_jobs I/O) mock'inami - testai neatlieka realių
tinklo/API kvietimų. Kiekvienas testas veikia izoliuotame tmp_path kataloge,
kad nepaliktų pėdsakų (run_manifest.json ir pan.) tikrame repo kataloge.
"""

from unittest.mock import patch

from manifest import (
    STATUS_ALL_API_CALLS_FAILED,
    STATUS_NO_SOURCES_CONFIGURED,
    STATUS_OK,
    STATUS_OK_NO_NEW_JOBS,
    STATUS_PREFLIGHT_FAILED,
)


@patch("main.load_sources")
@patch("main.preflight_check")
def test_main_stops_early_when_preflight_fails(mock_preflight, mock_load_sources, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_preflight.return_value = (False, "invalid API key")

    import main
    result = main.main()

    assert result.status == STATUS_PREFLIGHT_FAILED
    assert result.preflight_ok is False
    mock_load_sources.assert_not_called()  # preflight nepavykus, į scraping net neinama


@patch("main.scrape_all")
@patch("main.load_sources")
@patch("main.preflight_check")
def test_main_stops_when_no_sources_configured(mock_preflight, mock_load_sources, mock_scrape_all, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_preflight.return_value = (True, None)
    mock_load_sources.return_value = []

    import main
    result = main.main()

    assert result.status == STATUS_NO_SOURCES_CONFIGURED
    mock_scrape_all.assert_not_called()


@patch("main.rank_jobs")
@patch("main.deduplicate")
@patch("main.scrape_all")
@patch("main.load_sources")
@patch("main.preflight_check")
def test_main_ok_no_new_jobs_path(
    mock_preflight, mock_load_sources, mock_scrape_all, mock_deduplicate, mock_rank_jobs,
    tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    mock_preflight.return_value = (True, None)
    mock_load_sources.return_value = [{"name": "SourceA"}]
    mock_scrape_all.return_value = ([{"url": "https://x/1"}], [
        {"name": "SourceA", "attempts": 1, "successes": 1, "failures": 0,
         "jobs_found": 1, "circuit_breaker_skipped": False},
    ])
    mock_deduplicate.return_value = []  # viskas jau anksčiau matyta

    import main
    result = main.main()

    assert result.status == STATUS_OK_NO_NEW_JOBS
    mock_rank_jobs.assert_not_called()

    import json
    with open("matched_jobs.json") as f:
        assert json.load(f) == []


@patch("main.save_seen_urls")
@patch("main.load_seen_urls")
@patch("main.rank_jobs")
@patch("main.deduplicate")
@patch("main.scrape_all")
@patch("main.load_sources")
@patch("main.preflight_check")
def test_main_full_success_path(
    mock_preflight, mock_load_sources, mock_scrape_all, mock_deduplicate,
    mock_rank_jobs, mock_load_seen, mock_save_seen,
    tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    mock_preflight.return_value = (True, None)
    mock_load_sources.return_value = [{"name": "SourceA"}]
    mock_load_seen.return_value = set()
    new_job = {"url": "https://x/1", "title": "IT PM", "company": "Test", "source": "SourceA"}
    mock_scrape_all.return_value = ([new_job], [
        {"name": "SourceA", "attempts": 1, "successes": 1, "failures": 0,
         "jobs_found": 1, "circuit_breaker_skipped": False},
    ])
    mock_deduplicate.return_value = [new_job]
    matched_job = {**new_job, "match_score": 9, "match_reason": "Puikiai tinka"}
    mock_rank_jobs.return_value = ([matched_job], {"api_calls_made": 1, "api_call_errors": 0, "tool_calls_made": 0})

    import main
    result = main.main()

    assert result.status == STATUS_OK
    assert result.jobs_matched == 1
    mock_save_seen.assert_called_once()

    import json
    with open("matched_jobs.json") as f:
        saved = json.load(f)
    assert saved[0]["match_score"] == 9


@patch("main.save_seen_urls")
@patch("main.load_seen_urls")
@patch("main.rank_jobs")
@patch("main.deduplicate")
@patch("main.scrape_all")
@patch("main.load_sources")
@patch("main.preflight_check")
def test_main_all_api_calls_failed_status(
    mock_preflight, mock_load_sources, mock_scrape_all, mock_deduplicate,
    mock_rank_jobs, mock_load_seen, mock_save_seen,
    tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    mock_preflight.return_value = (True, None)
    mock_load_sources.return_value = [{"name": "SourceA"}]
    mock_load_seen.return_value = set()
    new_job = {"url": "https://x/1", "title": "X", "company": "Y", "source": "SourceA"}
    mock_scrape_all.return_value = ([new_job], [
        {"name": "SourceA", "attempts": 1, "successes": 1, "failures": 0,
         "jobs_found": 1, "circuit_breaker_skipped": False},
    ])
    mock_deduplicate.return_value = [new_job]
    mock_rank_jobs.return_value = ([], {"api_calls_made": 1, "api_call_errors": 1, "tool_calls_made": 0})

    import main
    result = main.main()

    assert result.status == STATUS_ALL_API_CALLS_FAILED


def test_main_entrypoint_exit_code_for_critical_status():
    """Patikrina CRITICAL_STATUSES rinkinio naudojimą - be subprocess (žr. taip pat
    test_main_integration.py realiam end-to-end patikrinimui su subprocess)."""
    from manifest import CRITICAL_STATUSES

    assert STATUS_PREFLIGHT_FAILED in CRITICAL_STATUSES
    assert STATUS_NO_SOURCES_CONFIGURED in CRITICAL_STATUSES
    assert STATUS_OK not in CRITICAL_STATUSES
    assert STATUS_OK_NO_NEW_JOBS not in CRITICAL_STATUSES


@patch("main.save_seen_urls")
@patch("main.load_seen_urls")
@patch("main.rank_jobs")
@patch("main.deduplicate")
@patch("main.scrape_all")
@patch("main.load_sources")
@patch("main.preflight_check")
def test_main_caps_jobs_sent_to_ranker_per_max_jobs_per_run(
    mock_preflight, mock_load_sources, mock_scrape_all, mock_deduplicate,
    mock_rank_jobs, mock_load_seen, mock_save_seen,
    tmp_path, monkeypatch,
):
    """
    KAINOS APSAUGA: jei naujų skelbimų daugiau nei config.MAX_JOBS_PER_RUN,
    rank_jobs() turi būti kviečiamas TIK su apribotu kiekiu, o likusieji
    NETURI būti pažymėti kaip "matyti" (kad būtų pervertinti kitą paleidimą).
    """
    import config
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "MAX_JOBS_PER_RUN", 2)  # dirbtinai maža riba testui

    mock_preflight.return_value = (True, None)
    mock_load_sources.return_value = [{"name": "SourceA"}]
    mock_load_seen.return_value = set()

    all_new_jobs = [
        {"url": f"https://x/{i}", "title": f"Job{i}", "company": "Y", "source": "SourceA"}
        for i in range(5)  # 5 nauji, bet limitas 2
    ]
    mock_scrape_all.return_value = (all_new_jobs, [
        {"name": "SourceA", "attempts": 1, "successes": 1, "failures": 0,
         "jobs_found": 5, "circuit_breaker_skipped": False},
    ])
    mock_deduplicate.return_value = all_new_jobs
    mock_rank_jobs.return_value = ([], {"api_calls_made": 2, "api_call_errors": 0, "tool_calls_made": 0, "ungrounded_count": 0})

    import main
    main.main()

    # rank_jobs turėjo gauti TIK 2 skelbimus (MAX_JOBS_PER_RUN), ne visus 5
    called_jobs_arg = mock_rank_jobs.call_args[0][0]
    assert len(called_jobs_arg) == 2

    # seen_urls atnaujintas TIK su tais 2, kurie realiai buvo įvertinti
    saved_urls = mock_save_seen.call_args[0][1]
    assert len(saved_urls) == 2
