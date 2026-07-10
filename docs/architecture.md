# Architektūra

## Duomenų srautas

```
┌─────────────────────┐
│   GitHub Actions     │   cron: kasdien 6:00 UTC arba rankinis paleidimas
│   (job-search.yml)   │
└──────────┬───────────┘
           │
           ▼
┌─────────────────────┐
│  Preflight Check      │   ranker.preflight_check()
│                       │   pigus (max_tokens=1) Claude API kvietimas -
│                       │   fail fast PRIEŠ brangų scraping, jei raktas/tinklas neveikia
└──────────┬───────────┘
           │ OK
           ▼
┌─────────────────────┐
│  Playwright Scraper  │   scraper.py
│  (sources.yaml /      │   PRIEŠ kiekvieną šaltinį: circuit_breaker.should_attempt()
│   sources.local.yaml) │   - jei OPEN (3+ nuoseklios ankstesnių paleidimų nesėkmės),
│  + Circuit Breaker     │   šaltinis praleidžiamas be jokio bandymo (24h cooldown)
│  + LYGIAGRETUS         │   Likusieji šaltiniai naršomi LYGIAGREČIAI (iki 3 vienu
│    vykdymas            │   metu, ThreadPoolExecutor) - kiekvienas nepriklausomas.
│                       │   Tam pačiam šaltiniui raktažodžiai vis tiek NUOSEKLIAI
│                       │   su mandagumo pauze (courtesy_pause_seconds)
└──────────┬───────────┘
           │  list[dict] + per-source stats (įsk. circuit_breaker_skipped)
           ▼
┌─────────────────────┐
│   Deduplicator       │   deduplicator.py
│                       │   pašalina dublikatus tarp raktažodžių + tarp paleidimų
│                       │   (seen_jobs.json)
└──────────┬───────────┘
           │  list[dict] (tik nauji)
           ▼
┌─────────────────────┐
│   Claude Ranker       │   ranker.py + prompts/ranking_prompt.md
│   (TOOL-CALLING       │   AGENT LOOP kiekvienam skelbimui:
│    AGENT LOOP)        │     1. Claude gauna snippet + įrankį get_full_job_description
│                       │     2. Jei reikia daugiau konteksto → PATS nusprendžia
│                       │        iškviesti įrankį (realiai atidaro puslapį per
│                       │        scraper.fetch_page_text())
│                       │     3. Kai turi info: grąžina {"score":1-10, "reason":...}
│                       │     Apsauga: max 3 iteracijos (MAX_AGENT_ITERATIONS)
└──────────┬───────────┘
           │  list[dict] (score >= MIN_MATCH_SCORE) + {api_calls_made, tool_calls_made}
           ▼
┌─────────────────────┐
│  Email Formatter      │   format_email.py
│                       │   matched_jobs.json → email_body.txt
└──────────┬───────────┘
           │
           ▼
┌─────────────────────┐
│   SMTP / Gmail        │   dawidd6/action-send-mail (workflow žingsnis)
│                       │   siunčia tik jei rasta bent 1 tinkamas skelbimas
└──────────────────────┘

Kiekvienas žingsnis aukščiau LOGINAMAS struktūrizuotai (logging_config.py -
JSON arba console, žr. "Structured Logging" skyrių žemiau) IR rašo į
RunManifest (manifest.py), kuris paleidimo pabaigoje išsaugomas kaip
run_manifest.json ir lemia exit code (žr. "Run Manifest" skyrių žemiau).
```

## Run Manifest - agento vykdymo stebėsena (observability)

**Problema, kurią sprendžia**: be šito, "0 naujų skelbimų" (normalu - tiesiog
nieko naujo neatsirado) ir "agentas iš viso nepasileido" (kritinė klaida -
blogas API raktas, tuščias `sources.yaml`, ar visi šaltiniai sugedę) iš
išorės atrodo IDENTIŠKAI. Kasdieniame automatiniame paleidime tai reiškia
tylų (silent) gedimą, kurio niekas nepastebi savaitėmis.

`manifest.py` fiksuoja kiekvieną pipeline žingsnį ir nustato vieną iš statusų:

| Statusas | Reikšmė | Exit code |
|---|---|---|
| `preflight_failed` | Claude API nepasiekiamas (blogas raktas, tinklas) | 1 (kritinis) |
| `no_sources_configured` | `sources.yaml`/`sources.local.yaml` tuščias | 1 (kritinis) |
| `all_sources_failed` | Visi šaltiniai sukonfigūruoti, bet nė vienas neveikė | 1 (kritinis) |
| `all_api_calls_failed` | Buvo naujų skelbimų, bet visi Claude kvietimai nepavyko | 1 (kritinis) |
| `ok_no_new_jobs` | Viskas veikė, tiesiog nieko naujo neatsirado | 0 (sėkmė) |
| `completed_with_errors` | Dalis API kvietimų nepavyko, bet ne visi | 0 (sėkmė su įspėjimu) |
| `ok` | Pilna sėkmė | 0 (sėkmė) |

`main.py` grąžina atitinkamą **exit code** operacinei sistemai/CI pagal šį
statusą (žr. `manifest.CRITICAL_STATUSES`) - tai reiškia, kad GitHub Actions
workflow **realiai paraus raudona varnele**, kai agentas nepasileido, o ne
tyliai "pavyks" su tuščiu rezultatu. Tai patikrinta realiu integraciniu testu
(`tests/test_main_integration.py`), kuris paleidžia `main.py` atskirame
procese be API rakto ir patvirtina, kad `exit code != 0`.

`run_manifest.json` pavyzdys (preflight nepavykus):
```json
{
  "started_at": "2026-07-06T16:57:21+00:00",
  "finished_at": "2026-07-06T16:57:21+00:00",
  "status": "preflight_failed",
  "preflight_ok": false,
  "preflight_error": "Could not resolve authentication method...",
  "sources_configured": 0,
  "source_stats": [],
  "jobs_scraped_total": 0,
  "jobs_new_after_dedup": 0,
  "api_calls_made": 0,
  "api_call_errors": 0,
  "jobs_matched": 0,
  "errors": ["Preflight patikra nepavyko: ..."]
}
```

## Circuit Breaker - apsauga nuo beprasmio pakartotinio bandymo

**Problema**: `tenacity` retry (žr. "Klaidų valdymas" žemiau) sprendžia
LAIKINAS klaidas VIENO paleidimo metu (pvz., trumpalaikis tinklo triktis).
Bet jei šaltinis nuosekliai fail'ina KELIS PALEIDIMUS iš eilės (pvz.,
svetainė pakeitė dizainą ir CSS selektorius nebeatpažįsta skelbimų), retry
nepadės - kiekvieną dieną vis tiek bandoma iš naujo, veltui eikvojant laiką.

**Sprendimas** (`circuit_breaker.py`): kiekvienam šaltiniui sekamas nuoseklių
PALEIDIMŲ (ne retry bandymų) nesėkmių skaičius, persistuojamas
`circuit_breaker_state.json` faile:

| Būsena | Reikšmė |
|---|---|
| `CLOSED` | Normalu - šaltinis bandomas kiekvieną paleidimą |
| `OPEN` | Po 3 nuoseklių nesėkmingų paleidimų - šaltinis PRALEIDŽIAMAS be jokio bandymo 24h |
| (half-open) | Po 24h automatiškai bandoma vėl - jei pavyksta → `CLOSED`, jei ne → vėl `OPEN` dar 24h |

Šis mechanizmas atspindimas `run_manifest.json` per
`source_stats[].circuit_breaker_skipped` lauką ir atskirą statusą
`all_sources_circuit_open` (žr. `manifest.py`) - **NĖRA** laikomas kritine
klaida (exit code 0), nes tai apsauga veikia taip, kaip suprojektuota, o ne
gedimas savaime.

## Structured Logging

Visi pipeline žingsniai logi'nami per Python `logging` (ne `print()`) su
JSON arba žmogui skaitomu formatu (`logging_config.py`, valdoma `LOG_FORMAT`
env kintamuoju). Kiekvienas įrašas turi `timestamp`, `level`, `logger`,
`message` + papildomus struktūrizuotus laukus (pvz., `source`, `keyword`,
`jobs_found`), perduodamus per `extra={}`.

```json
{"timestamp": "2026-07-06T17:42:15Z", "level": "INFO", "logger": "scraper",
 "message": "Paieška sėkminga", "source": "ExampleJobBoard1",
 "keyword": "product owner", "jobs_found": 5}
```

Paleidimo pabaigoje `manifest.log_summary(logger)` įrašo VISĄ
`run_manifest.json` turinį kaip vieną struktūrizuotą log įrašą
(`event=run_complete`) - naudinga log agregavimo sistemoms, jei logai
kaupiami centralizuotai (pvz., paieška `status=preflight_failed` per visus
praeitus paleidimus).

## Lygiagretus scraping (Parallel Execution)

**Problema**: iki šios versijos `scrape_all()` naršydavo VISUS
šaltinius×raktažodžius NUOSEKLIAI, su 2s mandagumo pauze po kiekvienos
užklausos. Su 3 šaltiniais ir 4 raktažodžiais tai reiškė ~24s vien
throttling'o, neskaičiuojant pačio naršymo laiko - su daugiau šaltinių
laikas augtų tiesiogiai proporcingai (neskalabilu).

**Sprendimas**: `scraper.scrape_all()` dabar naršo SKIRTINGUS šaltinius
LYGIAGREČIAI (`concurrent.futures.ThreadPoolExecutor`, numatytas limitas
`MAX_PARALLEL_SOURCES=3`), nes jie nepriklausomi vienas nuo kito (skirtingi
Chromium procesai, skirtingos svetainės). Raktažodžiai TAM PAČIAM šaltiniui
lieka naršomi NUOSEKLIAI su mandagumo pauze (`COURTESY_PAUSE_SECONDS=2`) -
lygiagretumas nepažeidžia mandagaus elgesio principo su konkrečia svetaine,
tik leidžia skirtingoms svetainėms nebelaukti viena kitos.

```
Sekvenciškai (senoji versija):    SourceA (4 raktažodžiai × ~2s) → SourceB (...) → SourceC (...)
                                   = ~24s+ vien pauzėms

Lygiagrečiai (dabartinė versija): SourceA (4 raktažodžiai × ~2s) ┐
                                   SourceB (4 raktažodžiai × ~2s) ├─ vykdoma VIENU METU
                                   SourceC (4 raktažodžiai × ~2s) ┘
                                   = ~8s (vieno šaltinio laikas, ne visų suma)
```

Abu parametrai konfigūruojami per `.env`/Secrets (`MAX_PARALLEL_SOURCES`,
`COURTESY_PAUSE_SECONDS`) - žr. `config.py`.

**Testais realiai įrodytas pagreitėjimas** (ne tik teigiamas kode) -
`tests/test_scraper_urls.py::test_scrape_all_runs_sources_in_parallel`
simuliuoja 3 šaltinius, kurių kiekvienas "užtrunka" 0.3s, ir patvirtina, kad
bendras vykdymo laikas < 0.7s (būtų ~0.9s+ sekvenciškai). Atskiras testas
(`test_scrape_all_respects_max_parallel_sources_limit`) patvirtina, kad
`max_parallel_sources=1` iš tikrųjų priverčia nuoseklų vykdymą - patikrina,
kad limitas realiai veikia, o ne ignoruojamas.

**Circuit breaker + lygiagretumas**: circuit breaker patikra
(`should_attempt`) atliekama PRIEŠ paleidžiant lygiagretų vykdymą (OPEN
šaltiniai apskritai nesiunčiami į `ThreadPoolExecutor`), o būsenos
atnaujinimas (`record_result`) - PO to, kai visi lygiagretūs darbai
baigėsi (nuosekliai, pagrindiniame thread'e - be lenktynių sąlygos
circuit breaker būsenos faile).

## Moduliai ir atsakomybės

| Modulis | Atsakomybė | Priklausomybės |
|---|---|---|
| `config.py` | Konfigūracijos skaitymas iš env/`.env` | `python-dotenv` |
| `scraper.py` | Naršymas ir duomenų ištraukimas (generinė funkcija visiems `sources.yaml` šaltiniams), automatinis retry laikinoms klaidoms, per-source statistika, circuit breaker integracija | `playwright`, `pyyaml`, `tenacity`, `circuit_breaker` |
| `circuit_breaker.py` | Šaltinių "sveikatos" sekimas tarp paleidimų - OPEN/CLOSED būsena, `circuit_breaker_state.json` | — |
| `deduplicator.py` | Dublikatų šalinimas, matytų skelbimų failo valdymas | — |
| `ranker.py` | TOOL-CALLING AGENT: vertinimas per Claude API su `get_full_job_description` įrankiu, JSON schema + grounding validacija (žr. docs/llm-reliability.md), automatinis retry, preflight healthcheck, prompt injection apsauga | `anthropic`, `tenacity`, `jsonschema`, `scraper` (tool vykdymui) |
| `manifest.py` | Vykdymo pėdsakas (execution trace) - statuso nustatymas, `run_manifest.json` | — |
| `logging_config.py` | Struktūrizuotas (JSON/console) logging visiems moduliams | — |
| `format_email.py` | JSON → skaitomas tekstas | — |
| `main.py` | Viso proceso orkestracija, `MAX_JOBS_PER_RUN` kainos apsauga, exit code pagal manifest statusą | visi aukščiau |

**Papildomi (ne-runtime) artefaktai:**
| Katalogas | Paskirtis |
|---|---|
| `schemas/rank_result.schema.json` | Formalus `ranker.score_job()` rezultato kontraktas (JSON Schema draft-07) |
| `eval/` | Eval harness - `dataset.json` (rankiniu būdu pažymėti skelbimai), `run_eval.py` (precision/recall skaičiavimas), `eval_results.md` (rezultatai) |
| `examples/` | Demo įėjimo/išėjimo duomenys - repo suprantamas be realaus paleidimo |

## Kodėl tokia architektūra

- **Kiekvienas modulis atsakingas už vieną dalyką** (single responsibility) —
  leidžia testuoti (žr. `tests/`) ir keisti dalis nepaliečiant kitų (pvz.,
  pridėti naują svetainę `scraper.py` nekeičiant `ranker.py`)
- **Duomenys tarp žingsnių keliauja kaip paprasti Python dict/JSON**, ne
  specializuotos klasės — lengva derinti (debug'inti) kiekvieną žingsnį
  atskirai, tiesiog atspausdinant tarpinį rezultatą
- **Persistencija (`seen_jobs.json`) atskirta nuo verslo logikos** —
  `deduplicator.py` nežino, iš kur atėjo skelbimai, `scraper.py` nežino, kad
  egzistuoja „matyta“ sąvoka
- **`ranker.py` yra tool-calling agentas, ne single-shot klasifikatorius** —
  Claude pats sprendžia, ar reikia iškviesti `get_full_job_description`
  (pilnas puslapio tekstas), o ne visada nuskaito visą puslapį (brangu) ar
  visada pasitenkina trumpu anonsu (netikslu). Pilnas paaiškinimas ir
  saugumo aspektai — `prompts/ranking_prompt.md`

## Kodėl tool-calling agentas, o ne single-shot klasifikacija

Ankstesnėje šio projekto versijoje `ranker.py` siųsdavo VIENĄ promptą su
snippet ir gaudavo atgal JSON - jokio sprendimo priėmimo, jokio papildomo
konteksto gavimo. Dabartinė versija leidžia modeliui pačiam nuspręsti, kada
trumpo anonso nepakanka:

- **Kaina/tikslumo balansas be žmogaus sprendimo**: vietoj "visada nuskaityti
  pilną puslapį" (brangu - kiekvienam skelbimui papildomas Playwright
  atidarymas) arba "niekada nenuskaityti" (netikslu - kai kurie anonsai per
  trumpi), agentas sprendžia individualiai kiekvienam skelbimui
- **Apsauga nuo begalinio ciklo**: `MAX_AGENT_ITERATIONS=3` - jei modelis vis
  kviečia įrankį ir nepasiekia galutinio atsakymo, laikoma klaida, ne
  užkabinimas
- **Klaidų izoliacija tarp žingsnių**: jei `get_full_job_description`
  nepavyksta (svetainė neatsidaro), tool_result pažymimas `is_error=True`, ir
  modelis GALI tęsti su tuo, ką jau turi (žr. testą
  `test_score_job_handles_tool_execution_failure_gracefully`), o ne visas
  vertinimas žlunga

## Klaidų valdymas (žr. taip pat docs/limitations.md)

| Scenarijus | Dabartinis elgesys |
|---|---|
| Svetainė neatsidaro / timeout (laikina tinklo klaida) | `scraper.py` automatiškai bando dar 2 kartus su eksponentiniu backoff (2s, 4s) per `tenacity`. Jei ir po 3 bandymų nepavyksta, klaida užloginama, tas šaltinis praleidžiamas, tęsiama su kitais |
| Claude API laikina klaida (rate limit, overload, tinklas, 5xx) | `ranker.py` automatiškai bando dar 2 kartus su eksponentiniu backoff (2s, 4s, iki 20s) per `tenacity`. Autentifikacijos/blogos užklausos klaidos (4xx, išskyrus rate limit) NEBANDOMOS kartoti, nes jos nepavyks ir kitą kartą |
| Claude API galutinai neatsako (po retry) arba grąžina netinkamą JSON | `ranker.py` sugauna išimtį, skelbimui priskiria `score=0` (nepatenka į atranką), tęsia su kitais skelbimais |
| El. laiško siuntimas nepavyksta | Workflow žingsnis pažymimas kaip failed, bet ankstesni žingsniai (rezultatų generavimas) jau įvykę — kitą kartą paleidus, `seen_jobs.json` jau atnaujintas, tad tie patys skelbimai nebus pervertinti (žinomas apribojimas — jei norite, kad email klaida nesutrukdytų `seen_jobs.json` atnaujinimo tvarkos, siųskite laišką prieš `seen_jobs.json` atnaujinimą) |
| Autentifikacijos/blogas API raktas | `ranker.preflight_check()` aptinka PRIEŠ scraping, `main.py` sustoja su `status=preflight_failed` ir exit code 1 - nešvaisto laiko scraping'ui, kuris vis tiek baigtųsi nesėkme |
| `get_full_job_description` įrankis nepavyksta (svetainė neatsidaro) | `ranker._execute_tool()` sugauna išimtį, grąžina `tool_result` su `is_error=True` - agent loop TĘSIASI, modelis gali baigti vertinimą su turima informacija, o ne visas `score_job()` žlunga |
| Agent loop viršija `MAX_AGENT_ITERATIONS` (modelis vis kviečia įrankį, nepasiekia galutinio atsakymo) | `ranker.py` sustabdo ciklą po 3 iteracijų, skelbimui priskiria `score=0`, tęsia su kitais skelbimais |
| Šaltinis nuosekliai fail'ina kelis PALEIDIMUS iš eilės (pvz., selektorius sugedo) | Po 3 nuoseklių paleidimų nesėkmių `circuit_breaker.py` "atidaro" šaltinį - kitą 24h jis praleidžiamas be jokio bandymo, apsaugant nuo beprasmio pakartotinio bandymo |
| 0 rezultatų iš scraperio | `manifest.py` atskiria priežastį: jei šaltiniai sukonfigūruoti ir bent vienas sėkmingai suveikė, bet nieko naujo neatsirado → `status=ok_no_new_jobs` (normalu, exit 0). Jei šaltinių sąrašas tuščias → `status=no_sources_configured` (exit 1). Jei visi šaltiniai sukonfigūruoti, bet visi bandymai nepavyko → `status=all_sources_failed` (exit 1). Jei visi šaltiniai praleisti dėl circuit breaker → `status=all_sources_circuit_open` (exit 0 - breaker veikia taip, kaip suprojektuota) |

## Galimi patobulinimai (neįgyvendinta šioje versijoje)

- **Plokščia modulių struktūra repo šaknyje** (`main.py`, `ranker.py`,
  `scraper.py`, `manifest.py`, `deduplicator.py`, `circuit_breaker.py`,
  `logging_config.py` ir kt. - visi vienoje vietoje, ne `src/job_agent/`
  paketo struktūroje su pakatalogiais `scraping/`, `ranking/`,
  `notifications/`, `observability/`). Tai **sąmoningai NEpataisyta** šioje
  versijoje - projekto dydžiui (9 moduliai, ~1840 LOC) plokščia struktūra
  vis dar valdoma, o pilnas perkėlimas į `src/` paketą pareikalautų
  atnaujinti visus importus, testus, CI workflow ir GitHub Actions kelius
  vienu metu, be galimybės realiai patikrinti visos grandinės (įskaitant
  GitHub Actions aplinką) prieš pateikiant pakeitimą - rizika sugadinti
  veikiantį pipeline nusveria naudą šiame etape. Jei projektas augtų
  (10+ modulių, keli tiekėjai, keli pipeline variantai), toks
  restruktūrizavimas taptų pateisinamas.
- Svertinis (weighted) scoring vietoj vieno bendro balo — žr. `docs/scoring.md`
- `sources.yaml` šiuo metu naudoja generinius CSS selektorius visiems šaltiniams
  (`job_link_substring` filtruoja pagal href); jei svetainės HTML struktūra
  labai skiriasi, gali prireikti selektorių override lauko per šaltinį
- Antras agento įrankis (pvz., `check_company_background`) - dabar tik vienas
  įrankis, tikslingai apribota apimtis (žr. `prompts/ranking_prompt.md`)
- Per-iteration structured logging agent loop sprendimams stebėti (dabar tik
  bendras `tool_calls_made` skaičius, be detalaus "kada ir kodėl" konteksto)
- Circuit breaker parametrai (`FAILURE_THRESHOLD=3`, `COOLDOWN_HOURS=24`)
  hardcoded konstantos - galėtų būti perkelti į `config.py`/env kintamuosius
- Nėra SLI/SLO formalizavimo (pvz., "95% paleidimų per mėnesį turi baigtis
  be kritinės klaidos") - `run_manifest.json` perrašomas kas paleidimą,
  istorija nekaupiama, tad tokio metriko skaičiuoti nėra iš ko
- `scraper.py` test coverage (73.7%) žemesnis nei kitų modulių (96-100%) -
  realaus tinklo/naršyklės navigacijos kodo negalima patikimai testuoti be
  arba realaus interneto ryšio (nepageidautina CI), arba gilaus Playwright
  API mock'inimo (mažai realios vertės). DOM parsinimo logika (didžiausia
  rizika) YRA pilnai padengta - žr. docs/testing.md "Test coverage" skyrių
- Lygiagretaus scraping limitas (`MAX_PARALLEL_SOURCES=3`) yra fiksuotas
  skaičius visiems šaltiniams vienodai - galimas patobulinimas: adaptyvus
  limitas pagal domeno rate limit atsakymus (pvz., HTTP 429), o ne statinė
  konstanta
