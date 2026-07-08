"""
Konfigūracija darbo paieškos agentui.

SVARBU (viešo repo saugumui):
Jautrūs duomenys (SEARCH_KEYWORDS, CANDIDATE_PROFILE) NĖRA rašomi tiesiai šiame
faile — jie skaitomi iš aplinkos kintamųjų. Taip kodas gali būti viešas
(pvz., portfolio), o jūsų realūs paieškos raktažodžiai ir CV profilis lieka
privatūs (lokaliai .env faile arba GitHub Secrets).

Jei aplinkos kintamieji nenustatyti, naudojami bendri pavyzdiniai duomenys —
tai leidžia bet kam paleisti šį projektą "demo" režimu be jūsų asmeninės info.
"""

import os

# python-dotenv leidžia lokaliai naudoti .env failą (žr. .env.example)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # produkcijoje (GitHub Actions) kintamieji ateina iš Secrets, dotenv nebūtinas


def _get_keywords():
    """SEARCH_KEYWORDS aplinkos kintamasis: raktažodžiai atskirti kableliu."""
    raw = os.environ.get("SEARCH_KEYWORDS")
    if raw:
        return [k.strip() for k in raw.split(",") if k.strip()]
    # Pavyzdiniai duomenys viešam demo naudojimui
    return ["projektu vadovas", "product owner"]


def _get_profile():
    """CANDIDATE_PROFILE aplinkos kintamasis: laisvo teksto CV santrauka."""
    return os.environ.get("CANDIDATE_PROFILE", (
        "Pavyzdinis kandidato profilis. Nustatykite CANDIDATE_PROFILE aplinkos "
        "kintamąjį (arba .env faile), kad agentas vertintų skelbimus pagal jūsų "
        "tikrą CV ir patirtį."
    ))


# Raktažodžiai, pagal kuriuos ieškoma
SEARCH_KEYWORDS = _get_keywords()

# Kandidato profilio santrauka, siunčiama Claude vertinimui
CANDIDATE_PROFILE = _get_profile()

# Minimalus atitikimo balas (1-10), nuo kurio skelbimas laikomas verčiu dėmesio
MIN_MATCH_SCORE = int(os.environ.get("MIN_MATCH_SCORE", "7"))

# Kiek skelbimų peržiūrėti per kiekvieną paiešką (per svetainę)
MAX_RESULTS_PER_SEARCH = int(os.environ.get("MAX_RESULTS_PER_SEARCH", "20"))

# Kiek šaltinių naršyti vienu metu (lygiagrečiai) - žr. scraper.scrape_all()
MAX_PARALLEL_SOURCES = int(os.environ.get("MAX_PARALLEL_SOURCES", "3"))

# Mandagumo pauzė (sekundėmis) tarp užklausų TAM PAČIAM šaltiniui
COURTESY_PAUSE_SECONDS = float(os.environ.get("COURTESY_PAUSE_SECONDS", "2"))

# KAINOS APSAUGA: maksimalus NAUJŲ (dar nematytų) skelbimų skaičius, kuris
# bus siunčiamas Claude API vertinimui per VIENĄ paleidimą. Jei scraperis
# netikėtai grąžina daugiau (pvz., pirmas paleidimas su daug istorinių
# skelbimų, ar sugedęs deduplikacijos loginė), likusieji tiesiog paliekami
# kitam paleidimui, o ne visi iškart nusiunčiami Claude - apsauga nuo
# netikėto API kaštų šuolio. Žr. main.py ir docs/cost-control.md.
MAX_JOBS_PER_RUN = int(os.environ.get("MAX_JOBS_PER_RUN", "50"))

# Failas, kuriame saugomi jau matyti skelbimų ID/nuorodos (kad nekartotų)
SEEN_JOBS_FILE = "seen_jobs.json"

# Failas, į kurį rašomi rezultatai
OUTPUT_FILE = "matched_jobs.json"

# Claude API modelis
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
