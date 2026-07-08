"""
Testai _extract_jobs_from_page() - REALIAI ištraukiama skelbimų informacija
iš statinio HTML fixture, naudojant tikrą Playwright/Chromium (be tinklo -
puslapis užkraunamas iš vietinio HTML per page.set_content(), ne per goto()).

Tai skiriasi nuo tests/test_scraper_urls.py, kuris testuoja tik URL
generavimo logiką - čia tikrinama pati sudėtingiausia dalis: DOM parsinimas,
dublikatų/nekorektiškų elementų praleidimas, santykinių/absoliučių URL
apdorojimas.
"""

import os

import pytest
from playwright.sync_api import sync_playwright

from scraper import _extract_jobs_from_page

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "generic_job_list.html")

TEST_SOURCE = {
    "name": "TestSource",
    "base_url": "https://jobs.example-one.test",
    "search_path": "/search",
    "query_param": "keyword",
    "job_link_substring": "/job/",
}


@pytest.fixture(scope="module")
def fixture_html():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def browser():
    """Viena bendra Playwright/Chromium instancija visiems šio modulio testams."""
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture(scope="module")
def playwright_page(browser, fixture_html):
    """Puslapis su užkrautu fixture HTML, be jokio tinklo kvietimo."""
    page = browser.new_page()
    page.set_content(fixture_html)
    yield page
    page.close()


def test_extract_jobs_finds_all_unique_links(playwright_page):
    results = _extract_jobs_from_page(playwright_page, TEST_SOURCE, max_results=20)

    # 3 unikalūs skelbimai (dublikatas ir "be href" elementas turi būti praleisti)
    assert len(results) == 3


def test_extract_jobs_deduplicates_by_href(playwright_page):
    results = _extract_jobs_from_page(playwright_page, TEST_SOURCE, max_results=20)

    urls = [job["url"] for job in results]
    assert len(urls) == len(set(urls)), "Turėtų nebūti dublikuotų URL tame pačiame puslapyje"


def test_extract_jobs_builds_absolute_url_from_relative_href(playwright_page):
    results = _extract_jobs_from_page(playwright_page, TEST_SOURCE, max_results=20)

    relative_job = next(j for j in results if "/job/1001" in j["url"])
    assert relative_job["url"] == "https://jobs.example-one.test/job/1001"


def test_extract_jobs_preserves_already_absolute_url(playwright_page):
    results = _extract_jobs_from_page(playwright_page, TEST_SOURCE, max_results=20)

    external_job = next(j for j in results if "external-full-url.test" in j["url"])
    assert external_job["url"] == "https://external-full-url.test/job/2001"


def test_extract_jobs_sets_correct_source_name(playwright_page):
    results = _extract_jobs_from_page(playwright_page, TEST_SOURCE, max_results=20)

    assert all(job["source"] == "TestSource" for job in results)


def test_extract_jobs_captures_title_and_company(playwright_page):
    results = _extract_jobs_from_page(playwright_page, TEST_SOURCE, max_results=20)

    it_job = next(j for j in results if "1001" in j["url"])
    assert "IT Projektų vadovas" in it_job["title"]
    assert "UAB Pavyzdinė Įmonė" in it_job["company"]


def test_extract_jobs_respects_max_results_limit(playwright_page):
    results = _extract_jobs_from_page(playwright_page, TEST_SOURCE, max_results=1)

    assert len(results) <= 1


def test_extract_jobs_empty_page_returns_empty_list(browser):
    page = browser.new_page()
    page.set_content("<html><body><p>Nėra jokių skelbimų.</p></body></html>")

    results = _extract_jobs_from_page(page, TEST_SOURCE, max_results=20)
    page.close()

    assert results == []


def test_fetch_page_text_returns_body_text(monkeypatch):
    """
    fetch_page_text() paleidžia savo Chromium instanciją, tad čia patikriname
    per monkeypatch, pakeisdami sync_playwright rezultatą fake objektu su
    fiksuotu HTML turiniu (be tikro naršyklės paleidimo šiam konkrečiam testui,
    kad testas liktų greitas ir izoliuotas nuo tinklo).
    """
    import scraper

    class FakePage:
        def goto(self, url, timeout=None):
            pass

        def wait_for_load_state(self, state, timeout=None):
            pass

        def inner_text(self, selector):
            return "Pilnas darbo skelbimo tekstas su visais reikalavimais."

    class FakeBrowser:
        def new_page(self, user_agent=None):
            return FakePage()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, headless=True):
            return FakeBrowser()

    class FakePlaywright:
        def __enter__(self):
            fake = type("obj", (), {"chromium": FakeChromium()})()
            return fake

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(scraper, "sync_playwright", lambda: FakePlaywright())

    result = scraper.fetch_page_text("https://example.test/job/1")

    assert "Pilnas darbo skelbimo tekstas" in result


def test_fetch_page_text_truncates_to_max_chars(monkeypatch):
    import scraper

    long_text = "A" * 5000

    class FakePage:
        def goto(self, url, timeout=None):
            pass

        def wait_for_load_state(self, state, timeout=None):
            pass

        def inner_text(self, selector):
            return long_text

    class FakeBrowser:
        def new_page(self, user_agent=None):
            return FakePage()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, headless=True):
            return FakeBrowser()

    class FakePlaywright:
        def __enter__(self):
            return type("obj", (), {"chromium": FakeChromium()})()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(scraper, "sync_playwright", lambda: FakePlaywright())

    result = scraper.fetch_page_text("https://example.test/job/1", max_chars=100)

    assert len(result) == 100
