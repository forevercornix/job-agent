"""
Run Manifest - agento paleidimo "vykdymo pėdsakas" (execution trace).

Tikslas: aiškiai atskirti "agentas pasileido ir tiesiog nieko naujo nerado"
nuo "agentas iš viso nepasileido / nutrūko dėl klaidos" - be šito abu
scenarijai iš išorės atrodo identiškai ("0 naujų skelbimų"), o tai yra
tylus (silent) gedimas, sunkiai pastebimas kasdieniame automatiniame paleidime.

Naudojimas (main.py):
    manifest = RunManifest()
    ok, err = ranker.preflight_check()
    manifest.set_preflight(ok, err)
    if not ok:
        manifest.finalize("preflight_failed")
        manifest.save()
        return
    ...
"""

import json
from datetime import datetime, timezone

MANIFEST_FILE = "run_manifest.json"

# Statusai, kuriuos gali įgauti manifest.status - kiekvienas atspindi
# SKIRTINGĄ priežastį, kodėl paleidimas baigėsi taip, kaip baigėsi.
STATUS_OK = "ok"
STATUS_OK_NO_NEW_JOBS = "ok_no_new_jobs"
STATUS_PREFLIGHT_FAILED = "preflight_failed"
STATUS_NO_SOURCES_CONFIGURED = "no_sources_configured"
STATUS_ALL_SOURCES_FAILED = "all_sources_failed"
STATUS_ALL_SOURCES_CIRCUIT_OPEN = "all_sources_circuit_open"
STATUS_ALL_API_CALLS_FAILED = "all_api_calls_failed"
STATUS_COMPLETED_WITH_ERRORS = "completed_with_errors"

# Statusai, kurie turėtų reikšti nenulinį exit code (main.py / CI supras,
# kad paleidimas realiai nepavyko, o ne tik "nieko naujo nerasta").
#
# PASTABA: STATUS_ALL_SOURCES_CIRCUIT_OPEN NEĮTRAUKTAS čia sąmoningai -
# circuit breaker veikia TAIP, KAIP SUPROJEKTUOTA (apsaugo nuo beprasmių
# bandymų), tai nėra "gedimas" pačia to žodžio prasme. Vis dėlto statusas
# atskirai matomas run_manifest.json, kad būtų pastebimas, jei visi
# šaltiniai liktų OPEN ilgą laiką.
CRITICAL_STATUSES = {
    STATUS_PREFLIGHT_FAILED,
    STATUS_NO_SOURCES_CONFIGURED,
    STATUS_ALL_SOURCES_FAILED,
    STATUS_ALL_API_CALLS_FAILED,
}


class RunManifest:
    """Kaupiama vykdymo statistika visam main.py paleidimui."""

    def __init__(self):
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished_at = None
        self.status = None

        self.preflight_ok = None
        self.preflight_error = None

        self.sources_configured = 0
        self.source_stats = []  # [{"name":..., "attempts":N, "successes":N, "failures":N, "jobs_found":N}]

        self.jobs_scraped_total = 0
        self.jobs_new_after_dedup = 0

        self.api_calls_made = 0
        self.api_call_errors = 0
        self.tool_calls_made = 0
        self.ungrounded_count = 0
        self.jobs_matched = 0

        self.errors = []

    def set_preflight(self, ok: bool, error: str = None):
        self.preflight_ok = ok
        self.preflight_error = error
        if not ok:
            self.errors.append(f"Preflight patikra nepavyko: {error}")

    def set_sources(self, sources: list):
        self.sources_configured = len(sources)

    def set_scrape_results(self, jobs_total: int, source_stats: list):
        self.jobs_scraped_total = jobs_total
        self.source_stats = source_stats
        for s in source_stats:
            if s.get("circuit_breaker_skipped"):
                self.errors.append(
                    f"Šaltinis '{s['name']}' praleistas - circuit breaker OPEN (per daug nuoseklių nesėkmių)"
                )
            elif s["attempts"] > 0 and s["successes"] == 0:
                self.errors.append(
                    f"Šaltinis '{s['name']}' - visi {s['attempts']} bandymai nepavyko"
                )

    def set_dedup_results(self, new_jobs_count: int):
        self.jobs_new_after_dedup = new_jobs_count

    def set_rank_results(
        self, api_calls_made: int, api_call_errors: int, jobs_matched: int,
        tool_calls_made: int = 0, ungrounded_count: int = 0,
    ):
        self.api_calls_made = api_calls_made
        self.api_call_errors = api_call_errors
        self.tool_calls_made = tool_calls_made
        self.ungrounded_count = ungrounded_count
        self.jobs_matched = jobs_matched
        if api_call_errors > 0:
            self.errors.append(f"{api_call_errors} Claude API kvietimai nepavyko (po retry)")
        if ungrounded_count > 0:
            self.errors.append(
                f"{ungrounded_count} vertinimai nužeminti - evidence trūko arba nerastas skelbimo tekste"
            )

    def determine_status(self) -> str:
        """
        Nustato galutinį statusą pagal sukauptą būseną. Tvarka svarbi -
        tikriname nuo kritiškiausios priežasties link mažiau kritiškos.
        """
        if self.preflight_ok is False:
            return STATUS_PREFLIGHT_FAILED
        if self.sources_configured == 0:
            return STATUS_NO_SOURCES_CONFIGURED
        if self.source_stats and all(s.get("circuit_breaker_skipped") for s in self.source_stats):
            return STATUS_ALL_SOURCES_CIRCUIT_OPEN
        if self.source_stats and all(s["successes"] == 0 for s in self.source_stats):
            return STATUS_ALL_SOURCES_FAILED
        if self.jobs_new_after_dedup == 0:
            return STATUS_OK_NO_NEW_JOBS
        if self.api_calls_made > 0 and self.api_call_errors == self.api_calls_made:
            return STATUS_ALL_API_CALLS_FAILED
        if self.errors:
            return STATUS_COMPLETED_WITH_ERRORS
        return STATUS_OK

    def finalize(self, status: str = None):
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.status = status or self.determine_status()

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "preflight_ok": self.preflight_ok,
            "preflight_error": self.preflight_error,
            "sources_configured": self.sources_configured,
            "source_stats": self.source_stats,
            "jobs_scraped_total": self.jobs_scraped_total,
            "jobs_new_after_dedup": self.jobs_new_after_dedup,
            "api_calls_made": self.api_calls_made,
            "api_call_errors": self.api_call_errors,
            "tool_calls_made": self.tool_calls_made,
            "ungrounded_count": self.ungrounded_count,
            "jobs_matched": self.jobs_matched,
            "errors": self.errors,
        }

    def save(self, path: str = MANIFEST_FILE):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def log_summary(self, logger) -> None:
        """
        Įrašo pilną manifest'ą kaip VIENĄ struktūrizuotą log įrašą (event=run_complete).
        Naudinga log agregavimo sistemoms (pvz., paieška "status=preflight_failed"
        per visus praeitus paleidimus, jei logai kaupiami centralizuotai).
        """
        logger.info("Paleidimo santrauka", extra={"event": "run_complete", **self.to_dict()})

    def print_summary(self):
        print(f"\n=== RUN MANIFEST: {self.status} ===")
        print(f"Preflight: {'OK' if self.preflight_ok else 'NEPAVYKO - ' + str(self.preflight_error)}")
        print(f"Šaltiniai: {self.sources_configured} sukonfigūruoti")
        for s in self.source_stats:
            print(f"  - {s['name']}: {s['successes']}/{s['attempts']} sėkmingi, {s['jobs_found']} skelbimų")
        print(f"Iš viso rasta: {self.jobs_scraped_total}, nauji: {self.jobs_new_after_dedup}")
        print(f"Claude API: {self.api_calls_made} kvietimų ({self.tool_calls_made} su tool use), {self.api_call_errors} klaidų")
        print(f"Negrounded (nužeminti dėl trūkstamo evidence): {self.ungrounded_count}")
        print(f"Atitiko: {self.jobs_matched}")
        if self.errors:
            print("Klaidos/įspėjimai:")
            for e in self.errors:
                print(f"  ! {e}")
