"""
Playwright scraperis, generinis visiems šaltiniams, aprašytiems sources.yaml.

SVARBU: Selektoriai (CSS klasės) yra geriausias spėjimas pagal svetainių
struktūrą paieškos metu. Svetainės keičia HTML, todėl PRIEŠ paleidimą:
  1. Atsidarykite paieškos puslapį naršyklėje
  2. Paspauskite F12 -> Inspect ant vieno skelbimo elemento
  3. Palyginkite su selektoriais žemiau ir pataisykite, jei reikia (žr. TODO žymes)

Paleidimui reikia: pip install playwright && playwright install chromium
"""

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

import yaml
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

import circuit_breaker
from logging_config import get_logger

logger = get_logger(__name__)

CIRCUIT_BREAKER_FILE = "circuit_breaker_state.json"

# Kiek šaltinių naršyti VIENU METU (lygiagrečiai). Skirtingi šaltiniai yra
# nepriklausomi (skirtingos svetainės), tad juos saugu naršyti lygiagrečiai -
# tai NEPAŽEIDŽIA mandagumo pauzės principo, nes pauzė (COURTESY_PAUSE_SECONDS)
# taikoma TARP UŽKLAUSŲ TAM PAČIAM ŠALTINIUI, o ne tarp skirtingų šaltinių.
# Konservatyvus skaičius (3), kad nebūtų per daug vienalaikių Chromium
# instancijų (kiekviena naudoja nemažai atminties).
MAX_PARALLEL_SOURCES = 3
COURTESY_PAUSE_SECONDS = 2

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SOURCES_FILE = "sources.yaml"          # viešas, generinis demo šablonas
SOURCES_LOCAL_FILE = "sources.local.yaml"  # privatus, realūs šaltiniai (gitignored)


def load_sources(path: str = None) -> list:
    """
    Įkelia šaltinių sąrašą.

    Pirmenybė teikiama `sources.local.yaml` (privatus, jūsų realūs šaltiniai,
    niekada necommit'inamas), o jei jo nėra - naudojamas viešas, generinis
    `sources.yaml` (demo pavyzdys, saugus rodyti viešame repo).

    Jei perduotas konkretus `path`, jis naudojamas tiesiogiai (naudinga testams).
    """
    if path is not None:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("sources", [])

    chosen_path = SOURCES_LOCAL_FILE if os.path.exists(SOURCES_LOCAL_FILE) else SOURCES_FILE
    with open(chosen_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("sources", [])


def build_search_url(source: dict, keyword: str) -> str:
    """
    Pagal šaltinio konfigūraciją ir raktažodį sudaro pilną paieškos URL.

    Palaiko neprivalomą "extra_query" lauką - fiksuotą papildomą query string
    dalį (pvz., "limit=20&offset=0"), kurios reikia kai kurioms svetainėms
    (pvz., cvonline.lt naudoja "keywords[0]=..." vietoj paprasto "keyword=...",
    kartu su limit/offset parametrais).

    Grynoji (pure) funkcija - lengva testuoti be naršyklės (žr. tests/).
    """
    base = source["base_url"].rstrip("/")
    path = source["search_path"]
    param = source["query_param"]
    url = f"{base}{path}?{param}={quote_plus(keyword)}"

    extra_query = source.get("extra_query")
    if extra_query:
        url += f"&{extra_query}"

    return url


def _slow_scroll(page, steps=4, pause=0.4):
    """Palaipsniui scrollina puslapį, kad įsikeltų 'lazy load' skelbimai."""
    for _ in range(steps):
        page.mouse.wheel(0, 1500)
        time.sleep(pause)


def _extract_jobs_from_page(page, source: dict, max_results: int) -> list:
    """
    Ištraukia skelbimus iš jau užkrauto paieškos puslapio.

    Palaiko DVI alternatyvias skelbimo nuorodų atpažinimo strategijas:
    - "job_link_substring": paprastas substring match href atribute (greitas,
      tinka svetainėms su aiškiu katalogo prefiksu, pvz. "/job/", "/lt/job/")
    - "job_link_regex": Python regex, tikrinamas KIEKVIENAM <a> elementui
      Python pusėje (lėčiau, bet reikalingas svetainėms be bendro prefikso,
      kur skelbimo URL tiesiog "{aprasomasis-slugas}-{skaitmeninis-id}" prie
      pat domeno šaknies, pvz. cv.lt: ".../produktu-vadovas-...-428799032")
    Naudojama TIK VIENA iš dviejų (regex turi pirmenybę, jei abu nurodyti).
    """
    base_url = source["base_url"].rstrip("/")
    job_link_regex = source.get("job_link_regex")

    if job_link_regex:
        pattern = re.compile(job_link_regex)
        all_links = page.query_selector_all("a[href]")
        cards = [link for link in all_links if link.get_attribute("href") and pattern.search(link.get_attribute("href"))]
    else:
        link_substring = source["job_link_substring"]
        # TODO: patikrinkite realų skelbimo kortelės selektorių Dev Tools įrankyje,
        # jei šis generinis selektorius nesuranda skelbimų jūsų svetainėje
        cards = page.query_selector_all(
            f"a[href*='{link_substring}'], article, div[class*='JobCard'], div[class*='job-item']"
        )

    results = []
    seen_urls = set()
    for card in cards[:max_results]:
        try:
            href = card.get_attribute("href")
            if not href and not job_link_regex:
                link_el = card.query_selector(f"a[href*='{source.get('job_link_substring', '')}']")
                href = link_el.get_attribute("href") if link_el else None
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)
            full_url = href if href.startswith("http") else f"{base_url}{href}"

            text = card.inner_text().strip()
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            title = lines[0] if lines else "N/A"
            company = lines[1] if len(lines) > 1 else "N/A"

            results.append({
                "source": source["name"],
                "title": title,
                "company": company,
                "url": full_url,
                "snippet": text[:500],
            })
        except Exception as e:
            logger.warning(
                "Praleistas skelbimo elementas dėl parsinimo klaidos",
                extra={"source": source["name"], "error": str(e)},
            )

    return results


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _load_page_with_retry(page, url: str):
    """
    Bando atidaryti puslapį iki 3 kartų su eksponentiniu backoff (2s, 4s, 8s...),
    jei nepavyksta dėl laikino tinklo/timeout klaidos. Po 3 nesėkmingų bandymų
    išimtis keliama toliau (reraise=True), kad ją sugautų scrape_source().

    SVARBU: page.goto() (pats puslapio įkėlimas) IR "networkidle" laukimas
    (visas foninis tinklo aktyvumas nutrūko) tvarkomi ATSKIRAI. Kai kurios
    šiuolaikinės svetainės (SPA su pokalbių valdikliais, analitikos/pranešimų
    signalais) NIEKADA nepasiekia "networkidle" - foninis tinklo aktyvumas
    tęsiasi be galo, nors pats puslapio turinys jau seniai įsikrovęs. Jei
    page.goto() PAVYKO, bet "networkidle" laukimas baigėsi timeout'u, tai
    NELAIKOMA klaida - DOM turinys tikriausiai jau yra, tęsiame toliau.
    Jei nepavyksta PATS goto() (realus tinklo/DNS/connection timeout), tai
    LIEKA tikra klaida ir keliama toliau įprastam retry.
    """
    page.goto(url, timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        logger.warning(
            "Puslapis įsikrovė, bet 'networkidle' nepasiekta per 15s - "
            "tikėtina, kad svetainė turi nuolatinį foninį tinklo aktyvumą "
            "(pokalbio valdiklis, analitika ir pan.). Tęsiama toliau, nes "
            "DOM turinys tikriausiai jau įkeltas.",
            extra={"url": url},
        )


def fetch_page_text(url: str, max_chars: int = 3000) -> str:
    """
    Nuskaito pilną puslapio tekstą (visible body text) iš nurodyto URL.

    Naudojama kaip AGENT ĮRANKIS (žr. ranker.py get_full_job_description) -
    kai skelbimo sąraše gautas snippet per trumpas/neaiškus patikimam
    vertinimui, agentas gali savarankiškai iškviesti šią funkciją, kad gautų
    pilną skelbimo puslapio tekstą.

    Grąžina apkarpytą tekstą (max_chars) - apsauga nuo per didelio token
    sunaudojimo, jei puslapis netikėtai didelis.

    Kelia išimtį klaidos atveju (kviečiantysis kodas - ranker.py - turi ją
    sugauti ir paversti į tool_result su is_error=True, o ne leisti kristi
    visam agent loop).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        try:
            _load_page_with_retry(page, url)
            text = page.inner_text("body").strip()
        finally:
            browser.close()
    return text[:max_chars]


def scrape_source(source: dict, keyword: str, max_results: int = 20) -> list:
    """Ieško vieno šaltinio pagal raktažodį. Grąžina sąrašą dict: title, company, url, snippet."""
    search_url = build_search_url(source, keyword)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        try:
            _load_page_with_retry(page, search_url)
            _slow_scroll(page)
            results = _extract_jobs_from_page(page, source, max_results)
        finally:
            browser.close()

    return results


def _scrape_one_source(source: dict, keywords: list, max_results_per_search: int, courtesy_pause_seconds: float) -> dict:
    """
    Naršo VIENĄ šaltinį per visus raktažodžius NUOSEKLIAI (su mandagumo
    pauze tarp užklausų tam pačiam šaltiniui). Ši funkcija kviečiama
    LYGIAGREČIAI keliems skirtingiems šaltiniams (žr. scrape_all žemiau) -
    todėl mandagumo pauzė tarp KEYWORDS tam pačiam šaltiniui išlieka, bet
    skirtingi šaltiniai nebelaukia vieni kitų.

    Grąžina dict: {"jobs": [...], "stats": {...}} - tik šiam VIENAM šaltiniui.
    Niekada nemeta išimties toliau (kiekviena keyword paieška apgaubta savo
    try/except) - tai svarbu, nes ThreadPoolExecutor ateityje naudojantis
    kodas turi galėti patikimai kviesti .result() kiekvienam future.
    """
    name = source["name"]
    jobs = []
    stats = {
        "name": name, "attempts": 0, "successes": 0, "failures": 0,
        "jobs_found": 0, "circuit_breaker_skipped": False,
    }

    for keyword in keywords:
        logger.info("Ieškoma šaltinyje", extra={"source": name, "keyword": keyword})
        stats["attempts"] += 1
        try:
            found = scrape_source(source, keyword, max_results_per_search)
            logger.info(
                "Paieška sėkminga", extra={"source": name, "keyword": keyword, "jobs_found": len(found)}
            )
            jobs.extend(found)
            stats["successes"] += 1
            stats["jobs_found"] += len(found)
        except Exception as e:
            logger.error(
                "Paieška nepavyko po pakartotinių bandymų",
                extra={"source": name, "keyword": keyword, "error": str(e)},
            )
            stats["failures"] += 1
        if courtesy_pause_seconds > 0:
            time.sleep(courtesy_pause_seconds)  # mandagumo pauzė tarp užklausų TAM PAČIAM šaltiniui

    return {"jobs": jobs, "stats": stats}


def scrape_all(
    keywords: list,
    max_results_per_search: int = 20,
    sources: list = None,
    cb_state_path: str = CIRCUIT_BREAKER_FILE,
    max_parallel_sources: int = MAX_PARALLEL_SOURCES,
    courtesy_pause_seconds: float = COURTESY_PAUSE_SECONDS,
) -> tuple:
    """
    Naršo visus šaltinius (iš sources.yaml, jei `sources` nenurodyta) visiems
    raktažodžiams. SKIRTINGI ŠALTINIAI naršomi LYGIAGREČIAI (iki
    `max_parallel_sources` vienu metu per ThreadPoolExecutor) - jie
    nepriklausomi vienas nuo kito (skirtingos svetainės, skirtingi Chromium
    procesai), tad lygiagretus vykdymas saugus ir žymiai sutrumpina bendrą
    vykdymo laiką. Tam pačiam šaltiniui raktažodžiai vis tiek naršomi
    NUOSEKLIAI su mandagumo pauze (`courtesy_pause_seconds`) - lygiagretumas
    NEPAŽEIDŽIA pauzės principo, taikomo tai pačiai svetainei.

    Grąžina (jobs, source_stats):
    - jobs: sujungtas visų rezultatų sąrašas
    - source_stats: [{"name":..., "attempts":N, "successes":N, "failures":N,
      "jobs_found":N, "circuit_breaker_skipped":bool}]
      naudojama run manifest'e, kad būtų aišku, ar kiekvienas šaltinis realiai
      veikė, ar visi bandymai jam nepavyko, ar jis buvo praleistas dėl
      circuit breaker (per daug nuoseklių nesėkmių ANKSTESNIUOSE paleidimuose).

    CIRCUIT BREAKER: jei šaltinis nuosekliai fail'ino
    circuit_breaker.FAILURE_THRESHOLD paleidimų iš eilės, jis laikinai
    praleidžiamas (be jokio bandymo) COOLDOWN_HOURS periodui - apsauga nuo
    beprasmio pakartotinio bandymo su akivaizdžiai sugedusiu selektoriumi/URL.
    Būsena persistuojama `cb_state_path` faile tarp paleidimų.

    Vieno šaltinio klaida (net po retry) nesustabdo viso proceso - klaida
    užloginama ir tęsiama su kitais šaltiniais/raktažodžiais.
    """
    if sources is None:
        sources = load_sources()

    cb_state = circuit_breaker.load_state(cb_state_path)

    all_jobs = []
    stats_by_source = {}
    sources_to_scrape = []

    # 1 žingsnis: circuit breaker patikra KIEKVIENAM šaltiniui PRIEŠ
    # lygiagretų naršymą - OPEN šaltiniai apskritai nesiunčiami į executor'ių.
    for source in sources:
        name = source["name"]
        if not circuit_breaker.should_attempt(cb_state, name):
            logger.warning(
                "Šaltinis praleistas - circuit breaker OPEN (per daug nuoseklių nesėkmių)",
                extra={"source": name, "event": "circuit_breaker_skip"},
            )
            stats_by_source[name] = {
                "name": name, "attempts": 0, "successes": 0, "failures": 0,
                "jobs_found": 0, "circuit_breaker_skipped": True,
            }
        else:
            sources_to_scrape.append(source)

    # 2 žingsnis: LYGIAGRETUS naršymas likusiems (ne circuit-open) šaltiniams.
    if sources_to_scrape:
        worker_count = min(max_parallel_sources, len(sources_to_scrape))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_source = {
                executor.submit(
                    _scrape_one_source, source, keywords, max_results_per_search, courtesy_pause_seconds
                ): source
                for source in sources_to_scrape
            }
            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    result = future.result()
                except Exception as e:
                    # Apsauginis atvejis - _scrape_one_source pati gaudo savo klaidas,
                    # tad čia pakliūtume tik netikėtos programavimo klaidos atveju.
                    logger.error(
                        "Netikėta klaida naršant šaltinį",
                        extra={"source": source["name"], "error": str(e)},
                    )
                    result = {
                        "jobs": [],
                        "stats": {
                            "name": source["name"], "attempts": 1, "successes": 0,
                            "failures": 1, "jobs_found": 0, "circuit_breaker_skipped": False,
                        },
                    }
                all_jobs.extend(result["jobs"])
                stats_by_source[result["stats"]["name"]] = result["stats"]

    # 3 žingsnis: circuit breaker atnaujinimas pagal ŠIO paleidimo rezultatus.
    for source in sources_to_scrape:
        name = source["name"]
        source_had_success = stats_by_source[name]["successes"] > 0
        cb_state = circuit_breaker.record_result(cb_state, name, success=source_had_success)

    circuit_breaker.save_state(cb_state, cb_state_path)
    return all_jobs, list(stats_by_source.values())
