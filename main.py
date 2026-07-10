"""
Pagrindinis skriptas: nuskaito skelbimus, filtruoja jau matytus, įvertina per Claude,
išsaugo ir parodo tinkamiausius. Paleisti: python main.py

Vykdymo eiga aiškiai fiksuojama RunManifest objekte (žr. manifest.py) ir
išsaugoma run_manifest.json - tai leidžia atskirti "agentas pasileido ir
tiesiog nieko naujo nerado" nuo "agentas iš viso nepasileido / sugedo".

Logging: struktūrizuotas (JSON arba console, žr. logging_config.py,
valdoma LOG_FORMAT aplinkos kintamuoju). Galutinė žmogui skaitoma santrauka
vis tiek atspausdinama per manifest.print_summary().
"""

import argparse
import json
import os
import sys
from datetime import datetime

import config
from deduplicator import deduplicate, load_seen_urls, save_seen_urls
from logging_config import get_logger, setup_logging
from manifest import STATUS_NO_SOURCES_CONFIGURED, STATUS_PREFLIGHT_FAILED, RunManifest
from ranker import preflight_check, rank_jobs
from scraper import load_sources, scrape_all

logger = get_logger(__name__)


def run_demo() -> None:
    """
    DEMO REŽIMAS: sugeneruoja PILNĄ el. laiško rezultato pavyzdį per KELIAS
    SEKUNDES, NENAUDOJANT jokio realaus Playwright scraping ar Claude API
    kvietimo - duomenys imami iš `examples/matched_jobs.example.json`
    (statinis, iš anksto paruoštas pavyzdys, ne gyvas rezultatas).

    PASKIRTIS: leisti bet kam, klonavusiam šį repo, per 1 komandą pamatyti,
    kaip atrodo GALUTINIS pipeline rezultatas (el. laiško formatas, laukai,
    struktūra), NEREIKALAUJANT ANTHROPIC_API_KEY, interneto ryšio, ar
    sukonfigūruotų realių šaltinių. Tai NĖRA realaus scraping/vertinimo
    demonstracija - tai tik IŠVESTIES FORMATO demonstracija.
    """
    print("=== DEMO REŽIMAS - pavyzdiniai duomenys, BE realaus scraping/Claude API kvietimo ===\n")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    examples_path = os.path.join(base_dir, "examples", "matched_jobs.example.json")

    with open(examples_path, "r", encoding="utf-8") as f:
        demo_jobs = json.load(f)

    with open("demo_matched_jobs.json", "w", encoding="utf-8") as f:
        json.dump(demo_jobs, f, ensure_ascii=False, indent=2)

    import format_email
    html_body = format_email.format_email_body_html(jobs=demo_jobs)
    with open("demo_email_preview.html", "w", encoding="utf-8") as f:
        f.write(html_body or "")

    text_body_lines = [
        f"[{job['match_score']}/10] {job['title']} @ {job['company']} ({job['source']})"
        for job in demo_jobs
    ]

    print(f"Rasta {len(demo_jobs)} pavyzdinių (NE realių) tinkamų skelbimų:\n")
    for line in text_body_lines:
        print(f"  {line}")

    print("\nSugeneruoti failai (pavyzdiniai, ne realaus paleidimo rezultatai):")
    print("  - demo_matched_jobs.json")
    print("  - demo_email_preview.html")
    print(
        "\nPASTABA: tai PAVYZDINIAI duomenys iš examples/matched_jobs.example.json, "
        "NE realaus scraping/Claude API vertinimo rezultatas. Realiam paleidimui "
        "naudokite 'python main.py' (be --demo) su sukonfigūruotu ANTHROPIC_API_KEY."
    )


def main() -> RunManifest:
    """Vykdo visą pipeline ir grąžina RunManifest - kviečiantysis (žr. apačioje)
    pagal jo statusą nusprendžia exit code."""
    logger.info("Darbo paieškos agentas paleistas", extra={"started_at": datetime.now().isoformat()})
    manifest = RunManifest()

    # 1. PREFLIGHT: patikriname Claude API pasiekiamumą PRIEŠ brangų scraping.
    # Fail fast - jei API raktas blogas ar tinklas neveikia, sužinome per
    # sekundę, ne po 10+ min. naršymo, kuris vis tiek baigtųsi nesėkme.
    logger.info("Preflight patikra (Claude API pasiekiamumas)...")
    ok, err = preflight_check(model=config.CLAUDE_MODEL)
    manifest.set_preflight(ok, err)
    if not ok:
        logger.critical("Preflight nepavyko - Claude API nepasiekiamas", extra={"error": err})
        manifest.finalize(STATUS_PREFLIGHT_FAILED)
        manifest.save()
        manifest.print_summary()
        manifest.log_summary(logger)
        return manifest
    logger.info("Preflight OK.")

    # 2. Šaltinių patikra - jei sources.yaml/sources.local.yaml tuščias arba
    # blogai sukonfigūruotas, tai NĖRA "0 naujų skelbimų" (normalu), o
    # konfigūracijos klaida (nenormalu) - reikia aiškiai atskirti.
    sources = load_sources()
    manifest.set_sources(sources)
    if not sources:
        logger.critical("sources.yaml/sources.local.yaml neturi jokių šaltinių")
        manifest.finalize(STATUS_NO_SOURCES_CONFIGURED)
        manifest.save()
        manifest.print_summary()
        manifest.log_summary(logger)
        return manifest

    seen_urls = load_seen_urls(config.SEEN_JOBS_FILE)
    logger.info("Anksčiau matyti skelbimai įkelti", extra={"seen_count": len(seen_urls)})

    all_jobs, source_stats = scrape_all(
        config.SEARCH_KEYWORDS,
        config.MAX_RESULTS_PER_SEARCH,
        sources=sources,
        max_parallel_sources=config.MAX_PARALLEL_SOURCES,
        courtesy_pause_seconds=config.COURTESY_PAUSE_SECONDS,
    )
    manifest.set_scrape_results(len(all_jobs), source_stats)
    logger.info("Scraping baigtas", extra={"jobs_scraped_total": len(all_jobs)})

    new_jobs = deduplicate(all_jobs, seen_urls)
    manifest.set_dedup_results(len(new_jobs))
    logger.info("Deduplikacija baigta", extra={"jobs_new": len(new_jobs)})

    if not new_jobs:
        logger.info("Naujų skelbimų nerasta - baigta")
        with open(config.OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        manifest.finalize()
        manifest.save()
        manifest.print_summary()
        manifest.log_summary(logger)
        return manifest

    # KAINOS APSAUGA: apribojame, kiek naujų skelbimų iš karto siunčiame
    # Claude API vertinimui vienam paleidimui (žr. config.MAX_JOBS_PER_RUN).
    # Skelbimai, kurie NEPATENKA į šį paleidimą, LIEKA "nematyti" (neįtraukiami
    # į seen_urls) - jie bus pervertinti KITAME paleidime, o ne prarasti.
    jobs_to_rank = new_jobs
    if len(new_jobs) > config.MAX_JOBS_PER_RUN:
        logger.warning(
            "Naujų skelbimų daugiau nei MAX_JOBS_PER_RUN - dalis atidedama kitam paleidimui",
            extra={"jobs_new": len(new_jobs), "max_jobs_per_run": config.MAX_JOBS_PER_RUN},
        )
        jobs_to_rank = new_jobs[:config.MAX_JOBS_PER_RUN]

    logger.info("Vertinama per Claude API (agent loop)...")
    matched, rank_stats = rank_jobs(
        jobs_to_rank,
        config.CANDIDATE_PROFILE,
        min_score=config.MIN_MATCH_SCORE,
        model=config.CLAUDE_MODEL,
    )
    manifest.set_rank_results(
        rank_stats["api_calls_made"],
        rank_stats["api_call_errors"],
        len(matched),
        tool_calls_made=rank_stats.get("tool_calls_made", 0),
        ungrounded_count=rank_stats.get("ungrounded_count", 0),
    )

    for job in matched:
        logger.info(
            "Tinkamas skelbimas",
            extra={
                "match_score": job["match_score"],
                "title": job["title"],
                "company": job["company"],
                "source": job["source"],
                "url": job["url"],
            },
        )

    with open(config.OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(matched, f, ensure_ascii=False, indent=2)
    logger.info("Rezultatai išsaugoti", extra={"file": config.OUTPUT_FILE, "jobs_matched": len(matched)})

    # Pažymime "matytais" TIK realiai įvertintus skelbimus (jobs_to_rank), ne
    # visą new_jobs - taip MAX_JOBS_PER_RUN atidėti skelbimai liks "nematyti"
    # ir bus pervertinti kitą paleidimą, o ne prarasti.
    seen_urls.update(job["url"] for job in jobs_to_rank)
    save_seen_urls(config.SEEN_JOBS_FILE, seen_urls)
    logger.info("Matytų skelbimų sąrašas atnaujintas", extra={"file": config.SEEN_JOBS_FILE})

    manifest.finalize()
    manifest.save()
    manifest.print_summary()
    manifest.log_summary(logger)
    return manifest


if __name__ == "__main__":
    from manifest import CRITICAL_STATUSES

    parser = argparse.ArgumentParser(description="Darbo paieškos agentas")
    parser.add_argument(
        "--demo", action="store_true",
        help="DEMO režimas: sugeneruoja pavyzdinį el. laiško rezultatą iš "
             "examples/ duomenų, BE realaus scraping ar Claude API kvietimo "
             "(nereikia ANTHROPIC_API_KEY ar interneto ryšio).",
    )
    args = parser.parse_args()

    setup_logging()  # LOG_FORMAT env kintamasis nustato json/console formatą

    if args.demo:
        run_demo()
        sys.exit(0)

    result_manifest = main()
    # Nenulinis exit code kritinėms klaidoms - GitHub Actions (ir bet kuris
    # kitas CI/cron) tada aiškiai parodys RAUDONĄ, ne žalią varnelę, kai
    # agentas realiai nepasileido/sugedo, o ne tik "nieko naujo nerado".
    if result_manifest.status in CRITICAL_STATUSES:
        sys.exit(1)
    sys.exit(0)
