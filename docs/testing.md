# Testai, kokybės patikra ir coverage

```bash
pip install pytest pytest-cov ruff
playwright install chromium   # reikalinga fixture-based scraping testams
pytest -v          # domeno logika + realus ThinHarness loop su scripted
                    # Model/ModelSession fake, email formatavimas (įsk. XSS
                    # apsaugos testai), run manifest statuso logika, circuit
                    # breaker būsenos pereigos, realus DOM parsinimas su
                    # Chromium (tests/fixtures/), realus subprocess
                    # integracinis testas, main.py orkestracijos unit testai
ruff check .        # lint patikra
```

Dauguma testų **neatlieka realių tinklo/API kvietimų**. `ranker.py` seam
testuose realus ThinHarness 0.6.0 ciklas gauna injectable scripted
`Model`/`ModelSession` fake: testuojamas tikras tool vykdymas, structured-output
retry, SSRF URL uždarymas, capacity ir safe fallback,
neperrašant ThinHarness implementacijos teste.

`tests/test_thinharness_dependency_contract.py` vykdo produkcinį `score_job()`
su realiu Anthropic provider ir `httpx.MockTransport`. Jis tikrina provider
retry, pokalbio išlaikymą ir non-retryable 4xx elgesį be išorinio tinklo.

`tests/test_scraper_extraction.py` naudoja **tikrą Chromium naršyklę**
(be tinklo — puslapis užkraunamas iš vietinio HTML per `page.set_content()`),
kad realiai patikrintų sudėtingiausią scraping dalį — DOM parsinimą,
dublikatų šalinimą, santykinių/absoliučių URL apdorojimą. Tam reikalingas
`playwright install chromium` prieš paleidžiant testus.

## Test coverage

```bash
pytest --cov=. --cov-report=term-missing
```

Lokali coverage patikra viršija `pyproject.toml` nustatytą CI ribą. CI
(`ci.yml`) vykdo testus su `--cov-fail-under=85`, todėl žemesnė coverage
reikšmė sustabdo build.

`scraper.py` coverage yra žemesnė už kitų modulių. Priežastis: `scrape_source()`, realaus
puslapio navigacijos ir retry logikos dalys reikalauja TIKRO tinklo/naršyklės
kvietimo į realią svetainę - jų negalima patikimai testuoti be arba (a) realaus
interneto ryšio testų metu (nepageidautina CI aplinkoje - trapu, lėta,
priklauso nuo trečiųjų šalių), arba (b) itin gilaus Playwright vidinio API
mock'inimo, kuris duotų mažai realios vertės (testuotų mock'ą, ne realią
logiką). DOM parsinimo logika (`_extract_jobs_from_page`, sudėtingiausia ir
rizikingiausia dalis) YRA pilnai padengta per fixture-based testus
(`tests/test_scraper_extraction.py`) - būtent tai buvo prioritetas, ne
100% eilutės coverage vien dėl skaičiaus.

`.github/workflows/ci.yml` automatiškai paleidžia abu žingsnius (lint + testai,
įskaitant Chromium diegimą) kiekvienam push/PR į `main`.
