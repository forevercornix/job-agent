"""
Circuit breaker darbo skelbimų šaltiniams.

PROBLEMA, kurią sprendžia: be circuit breaker, jei šaltinis nuosekliai
fail'ina (pvz., svetainė pakeitė dizainą ir CSS selektorius nebeveikia),
KIEKVIENĄ paleidimą vis tiek bandoma iš naujo (su pilnu retry ciklu), veltui
eikvojant laiką ir apkraunant svetainę užklausomis, kurios akivaizdžiai
nepavyks.

SPRENDIMAS: po N nuoseklių nesėkmių (skirtingi paleidimai, ne tik retry
vieno paleidimo viduje) šaltinis "atidaromas" (OPEN) - laikinai praleidžiamas
be jokio bandymo. Po COOLDOWN_HOURS automatiškai bandoma vėl (half-open) -
jei pavyksta, grąžinama į CLOSED būseną, jei ne - liekama OPEN dar
COOLDOWN_HOURS.

Būsena persistuojama tarp paleidimų faile (circuit_breaker_state.json),
kad "nuoseklumas" būtų skaičiuojamas per realius, atskirus cron paleidimus,
o ne per retry bandymus vieno paleidimo metu (tam jau yra tenacity retry
scraper.py/ranker.py).
"""

import json
import os
from datetime import datetime, timedelta, timezone

STATE_FILE = "circuit_breaker_state.json"

FAILURE_THRESHOLD = 3   # po tiek NUOSEKLIŲ PALEIDIMŲ nesėkmių - atidaroma
COOLDOWN_HOURS = 24      # kiek laiko šaltinis praleidžiamas prieš half-open bandymą

CLOSED = "closed"   # normalu - bandoma kaip įprasta
OPEN = "open"        # laikinai praleidžiama (per daug nuoseklių nesėkmių)


def load_state(path: str = STATE_FILE) -> dict:
    """Įkelia visų šaltinių circuit breaker būseną. Tuščias dict, jei failo nėra."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict, path: str = STATE_FILE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _get_source_state(state: dict, source_name: str) -> dict:
    """Grąžina šaltinio būseną arba numatytąją (CLOSED, 0 nesėkmių), jei dar nematyta."""
    return dict(state.get(source_name, {
        "status": CLOSED,
        "consecutive_failures": 0,
        "opened_at": None,
        "last_success": None,
    }))


def should_attempt(state: dict, source_name: str, cooldown_hours: int = COOLDOWN_HOURS, now=None) -> bool:
    """
    Grąžina True, jei šaltinio verta bandyti šiame paleidime.

    CLOSED -> visada True.
    OPEN -> True tik jei praėjo >= cooldown_hours nuo atidarymo (half-open
    bandymas), kitaip False (praleidžiama).
    """
    now = now or datetime.now(timezone.utc)
    source_state = _get_source_state(state, source_name)

    if source_state["status"] == CLOSED:
        return True

    opened_at_raw = source_state.get("opened_at")
    if not opened_at_raw:
        return True  # apsauginis atvejis - jei OPEN, bet nėra opened_at, leidžiam bandyti

    opened_at = datetime.fromisoformat(opened_at_raw)
    return now - opened_at >= timedelta(hours=cooldown_hours)


def record_result(
    state: dict,
    source_name: str,
    success: bool,
    failure_threshold: int = FAILURE_THRESHOLD,
    now=None,
) -> dict:
    """
    Atnaujina šaltinio būseną pagal ŠIO PALEIDIMO rezultatą (bent viena
    sėkmė tarp visų raktažodžių = success, visos nesėkmės = failure).

    Sėkmė -> iškart CLOSED, skaitliukas nulinamas (half-open bandymas pavyko).
    Nesėkmė -> +1 prie consecutive_failures; jei pasiekia failure_threshold -> OPEN.

    Grąžina atnaujintą PILNĄ state dict (su visais šaltiniais, ne tik šiuo).
    """
    now = now or datetime.now(timezone.utc)
    source_state = _get_source_state(state, source_name)

    if success:
        source_state["status"] = CLOSED
        source_state["consecutive_failures"] = 0
        source_state["opened_at"] = None
        source_state["last_success"] = now.isoformat()
    else:
        source_state["consecutive_failures"] += 1
        if source_state["consecutive_failures"] >= failure_threshold:
            source_state["status"] = OPEN
            source_state["opened_at"] = now.isoformat()

    state[source_name] = source_state
    return state
