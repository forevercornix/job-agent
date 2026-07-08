"""Testai scraper.py URL generavimo ir sources.yaml įkėlimo logikai (be naršyklės)."""

from unittest.mock import patch

import pytest

from scraper import build_search_url, load_sources


def test_build_search_url_basic():
    source = {
        "base_url": "https://www.example.lt",
        "search_path": "/search",
        "query_param": "keyword",
    }
    url = build_search_url(source, "projektu vadovas")
    assert url == "https://www.example.lt/search?keyword=projektu+vadovas"


def test_build_search_url_strips_trailing_slash_from_base():
    source = {
        "base_url": "https://www.example.lt/",  # su trailing slash
        "search_path": "/search",
        "query_param": "q",
    }
    url = build_search_url(source, "test")
    assert url == "https://www.example.lt/search?q=test"


def test_build_search_url_encodes_special_characters():
    source = {
        "base_url": "https://www.example.lt",
        "search_path": "/search",
        "query_param": "keyword",
    }
    url = build_search_url(source, "product owner & IT")
    assert "product+owner" in url
    assert " " not in url


def test_load_sources_returns_expected_structure():
    sources = load_sources("sources.yaml")

    assert isinstance(sources, list)
    assert len(sources) == 2

    names = {s["name"] for s in sources}
    assert names == {"ExampleJobBoard1", "ExampleJobBoard2"}

    for source in sources:
        assert "base_url" in source
        assert "search_path" in source
        assert "query_param" in source
        assert "job_link_substring" in source


def test_load_sources_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_sources("does_not_exist.yaml")


def test_build_search_url_works_for_all_real_sources():
    """Patikrina, kad visiems sources.yaml įrašams URL generuojasi be klaidų."""
    sources = load_sources("sources.yaml")
    for source in sources:
        url = build_search_url(source, "test raktazodis")
        assert url.startswith(source["base_url"])
        assert source["query_param"] in url


def test_load_sources_prefers_local_file_over_public(tmp_path, monkeypatch):
    """
    Patikrina privatumo mechanizmą: jei egzistuoja sources.local.yaml,
    load_sources() (be aiškaus path) turi naudoti JĮ, ne viešą sources.yaml.
    """
    import scraper

    local_file = tmp_path / "sources.local.yaml"
    local_file.write_text(
        "sources:\n  - name: PrivateRealSite\n    base_url: 'https://real.example'\n"
        "    search_path: '/s'\n    query_param: 'q'\n    job_link_substring: '/job/'\n"
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scraper, "SOURCES_LOCAL_FILE", "sources.local.yaml")
    monkeypatch.setattr(scraper, "SOURCES_FILE", "sources.yaml")  # neegzistuoja tmp_path'e

    sources = scraper.load_sources()

    assert len(sources) == 1
    assert sources[0]["name"] == "PrivateRealSite"


def test_load_sources_falls_back_to_public_when_no_local_file(tmp_path, monkeypatch):
    """Jei sources.local.yaml nėra, naudojamas viešas sources.yaml."""
    import shutil

    import scraper

    shutil.copy("sources.yaml", tmp_path / "sources.yaml")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scraper, "SOURCES_LOCAL_FILE", "sources.local.yaml")  # neegzistuoja

    sources = scraper.load_sources()

    names = {s["name"] for s in sources}
    assert names == {"ExampleJobBoard1", "ExampleJobBoard2"}


@patch("scraper.scrape_source")
def test_scrape_all_aggregates_stats_per_source(mock_scrape_source, tmp_path):
    """Patikrina, kad scrape_all teisingai suskaičiuoja attempts/successes/jobs_found kiekvienam šaltiniui."""
    import scraper

    source_a = {"name": "SourceA", "base_url": "https://a.test", "search_path": "/s",
                "query_param": "q", "job_link_substring": "/job/"}
    source_b = {"name": "SourceB", "base_url": "https://b.test", "search_path": "/s",
                "query_param": "q", "job_link_substring": "/job/"}

    # SourceA visada randa 2 skelbimus, SourceB visada meta klaidą
    def fake_scrape(source, keyword, max_results):
        if source["name"] == "SourceA":
            return [{"url": f"https://a.test/job/{keyword}-1"}, {"url": f"https://a.test/job/{keyword}-2"}]
        raise TimeoutError("simuliuota tinklo klaida")

    mock_scrape_source.side_effect = fake_scrape
    cb_path = str(tmp_path / "cb_state.json")

    jobs, stats = scraper.scrape_all(
        ["kw1", "kw2"], max_results_per_search=10, sources=[source_a, source_b],
        cb_state_path=cb_path, courtesy_pause_seconds=0,
    )

    assert len(jobs) == 4  # 2 raktažodžiai x 2 skelbimai iš SourceA

    stats_by_name = {s["name"]: s for s in stats}
    assert stats_by_name["SourceA"]["attempts"] == 2
    assert stats_by_name["SourceA"]["successes"] == 2
    assert stats_by_name["SourceA"]["failures"] == 0
    assert stats_by_name["SourceA"]["jobs_found"] == 4
    assert stats_by_name["SourceA"]["circuit_breaker_skipped"] is False

    assert stats_by_name["SourceB"]["attempts"] == 2
    assert stats_by_name["SourceB"]["successes"] == 0
    assert stats_by_name["SourceB"]["failures"] == 2
    assert stats_by_name["SourceB"]["jobs_found"] == 0
    assert stats_by_name["SourceB"]["circuit_breaker_skipped"] is False


@patch("scraper.scrape_source")
def test_scrape_all_empty_sources_returns_empty(mock_scrape_source, tmp_path):
    import scraper

    jobs, stats = scraper.scrape_all(["kw"], sources=[], cb_state_path=str(tmp_path / "cb_state.json"), courtesy_pause_seconds=0)

    assert jobs == []
    assert stats == []
    mock_scrape_source.assert_not_called()


@patch("scraper.scrape_source")
def test_scrape_all_skips_source_with_open_circuit_breaker(mock_scrape_source, tmp_path):
    """Šaltinis su OPEN circuit breaker turi būti praleistas be jokio bandymo."""
    import circuit_breaker as cb
    import scraper

    source_a = {"name": "BadSource", "base_url": "https://a.test", "search_path": "/s",
                "query_param": "q", "job_link_substring": "/job/"}
    cb_path = str(tmp_path / "cb_state.json")

    # Iš anksto paruošiame būseną, kur BadSource jau OPEN (ankstesnių paleidimų nesėkmės)
    state = {}
    for _ in range(cb.FAILURE_THRESHOLD):
        state = cb.record_result(state, "BadSource", success=False)
    cb.save_state(state, cb_path)

    jobs, stats = scraper.scrape_all(["kw"], sources=[source_a], cb_state_path=cb_path, courtesy_pause_seconds=0)

    assert jobs == []
    assert stats[0]["circuit_breaker_skipped"] is True
    assert stats[0]["attempts"] == 0
    mock_scrape_source.assert_not_called()


@patch("scraper.scrape_source")
def test_scrape_all_updates_circuit_breaker_state_after_run(mock_scrape_source, tmp_path):
    """Po sėkmingo paleidimo circuit breaker būsena turi likti/tapti CLOSED ir būti išsaugota faile."""
    import circuit_breaker as cb
    import scraper

    source_a = {"name": "SourceA", "base_url": "https://a.test", "search_path": "/s",
                "query_param": "q", "job_link_substring": "/job/"}
    mock_scrape_source.return_value = [{"url": "https://a.test/job/1"}]
    cb_path = str(tmp_path / "cb_state.json")

    scraper.scrape_all(["kw"], sources=[source_a], cb_state_path=cb_path, courtesy_pause_seconds=0)

    saved_state = cb.load_state(cb_path)
    assert saved_state["SourceA"]["status"] == cb.CLOSED


@patch("scraper.scrape_source")
def test_scrape_all_runs_sources_in_parallel(mock_scrape_source, tmp_path):
    """
    REALUS ĮRODYMAS lygiagretumo: 3 šaltiniai, kiekvienas "užtrunka" 0.3s
    (simuliuota time.sleep scrape_source viduje). Jei naršoma NUOSEKLIAI,
    bendras laikas būtų ~0.9s+. Lygiagrečiai (max_parallel_sources=3) turėtų
    užtrukti ~0.3-0.5s (visi trys vienu metu).
    """
    import time

    import scraper

    def slow_scrape(source, keyword, max_results):
        time.sleep(0.3)
        return [{"url": f"https://{source['name']}.test/job/1"}]

    mock_scrape_source.side_effect = slow_scrape

    sources = [
        {"name": f"Source{i}", "base_url": f"https://s{i}.test", "search_path": "/s",
         "query_param": "q", "job_link_substring": "/job/"}
        for i in range(3)
    ]
    cb_path = str(tmp_path / "cb_state.json")

    start = time.perf_counter()
    jobs, stats = scraper.scrape_all(
        ["kw"], sources=sources, cb_state_path=cb_path,
        courtesy_pause_seconds=0, max_parallel_sources=3,
    )
    elapsed = time.perf_counter() - start

    assert len(jobs) == 3  # po 1 skelbimą iš kiekvieno šaltinio
    # Sekvenciškai būtų ~0.9s (3 x 0.3s); lygiagrečiai turėtų būti gerokai
    # mažiau - naudojame dosnią 0.7s ribą, kad testas nebūtų trapus (flaky)
    # lėtesnėse CI mašinose, bet vis tiek aiškiai atskirtų nuo sekvencinio elgesio.
    assert elapsed < 0.7, f"Tikėtasi lygiagretaus vykdymo (<0.7s), gauta {elapsed:.2f}s - ar tikrai lygiagretu?"


@patch("scraper.scrape_source")
def test_scrape_all_respects_max_parallel_sources_limit(mock_scrape_source, tmp_path):
    """
    Su max_parallel_sources=1, 3 šaltiniai TURI būti naršomi nuosekliai
    (ne lygiagrečiai) - patikrina, kad limitas realiai veikia, o ne
    ignoruojamas.
    """
    import time

    import scraper

    def slow_scrape(source, keyword, max_results):
        time.sleep(0.2)
        return [{"url": f"https://{source['name']}.test/job/1"}]

    mock_scrape_source.side_effect = slow_scrape

    sources = [
        {"name": f"Source{i}", "base_url": f"https://s{i}.test", "search_path": "/s",
         "query_param": "q", "job_link_substring": "/job/"}
        for i in range(3)
    ]
    cb_path = str(tmp_path / "cb_state.json")

    start = time.perf_counter()
    scraper.scrape_all(
        ["kw"], sources=sources, cb_state_path=cb_path,
        courtesy_pause_seconds=0, max_parallel_sources=1,
    )
    elapsed = time.perf_counter() - start

    # Su max_parallel_sources=1 turi būti ~0.6s (3 x 0.2s nuosekliai), ne ~0.2s
    assert elapsed >= 0.55, f"Su max_parallel_sources=1 tikėtasi nuoseklaus vykdymo (>=0.55s), gauta {elapsed:.2f}s"


@patch("scraper._scrape_one_source")
def test_scrape_all_handles_unexpected_exception_in_worker(mock_scrape_one_source, tmp_path):
    """
    Apsauginis atvejis: jei _scrape_one_source (per klaidą kode) mestų
    nesugautą išimtį, scrape_all neturi crash'intis - turi užloginti klaidą
    ir tęsti su kitais šaltiniais.
    """
    import scraper

    def side_effect(source, keywords, max_results_per_search, courtesy_pause_seconds):
        if source["name"] == "BadSource":
            raise RuntimeError("netikėta programavimo klaida")
        return {"jobs": [{"url": "https://good.test/job/1"}],
                "stats": {"name": source["name"], "attempts": 1, "successes": 1,
                          "failures": 0, "jobs_found": 1, "circuit_breaker_skipped": False}}

    mock_scrape_one_source.side_effect = side_effect

    sources = [
        {"name": "BadSource", "base_url": "https://bad.test", "search_path": "/s",
         "query_param": "q", "job_link_substring": "/job/"},
        {"name": "GoodSource", "base_url": "https://good.test", "search_path": "/s",
         "query_param": "q", "job_link_substring": "/job/"},
    ]
    cb_path = str(tmp_path / "cb_state.json")

    jobs, stats = scraper.scrape_all(["kw"], sources=sources, cb_state_path=cb_path, courtesy_pause_seconds=0)

    stats_by_name = {s["name"]: s for s in stats}
    assert stats_by_name["GoodSource"]["successes"] == 1
    assert stats_by_name["BadSource"]["failures"] == 1
    assert len(jobs) == 1  # tik iš GoodSource
