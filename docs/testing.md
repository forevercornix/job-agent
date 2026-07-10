# Testai, kokybės patikra ir coverage

```bash
pip install pytest pytest-cov ruff
playwright install chromium   # reikalinga fixture-based scraping testams
pytest -v          # 187 testai: deduplikacija, ranker agent loop (mock'intas
                    # Claude API + tool use), email formatavimas (įsk. XSS
                    # apsaugos testai), run manifest statuso logika, circuit
                    # breaker būsenos pereigos, realus DOM parsinimas su
                    # Chromium (tests/fixtures/), realus subprocess
                    # integracinis testas, main.py orkestracijos unit testai
ruff check .        # lint patikra
```

Dauguma testų **neatlieka realių tinklo/API kvietimų** — `ranker.py` testuose
Anthropic klientas yra mock'intas (`unittest.mock.patch`). Tačiau
`tests/test_scraper_extraction.py` naudoja **tikrą Chromium naršyklę**
(be tinklo — puslapis užkraunamas iš vietinio HTML per `page.set_content()`),
kad realiai patikrintų sudėtingiausią scraping dalį — DOM parsinimą,
dublikatų šalinimą, santykinių/absoliučių URL apdorojimą. Tam reikalingas
`playwright install chromium` prieš paleidžiant testus.

## Test coverage

```bash
pytest --cov=. --cov-report=term-missing
```

**Realiai išmatuotas rezultatas: 92.9%** (187 testai, žr. `pyproject.toml`
`[tool.coverage]` konfigūraciją). CI (`ci.yml`) vykdo testus su
`--cov-fail-under=85` - jei coverage nukris žemiau 85%, CI sulūš.

Sąžininga pastaba dėl vieno modulio: `scraper.py` turi tik **73.7%** coverage
(likusieji moduliai — 96-100%). Priežastis: `scrape_source()`, realaus
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
