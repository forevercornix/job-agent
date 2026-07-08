# Deployment (paleidimas ir automatizavimas)

## Vienkartinis paleidimas

```bash
python main.py
```

Skriptas:
1. **Preflight**: pigus Claude API kvietimas, patvirtinantis, kad raktas/tinklas
   veikia - jei ne, sustoja iš karto (exit code 1), nešvaisto laiko scraping'ui
2. Nuskaito naujus skelbimus iš visų sukonfigūruotų šaltinių pagal jūsų raktažodžius
3. Praleidžia jau anksčiau matytus (saugoma `seen_jobs.json`, taip pat gitignore'inta)
4. Kiekvieną naują skelbimą įvertina per Claude API (1–10 balų atitikimas)
5. Parodo terminale ir išsaugo `matched_jobs.json` tik tuos, kurie pasiekė `MIN_MATCH_SCORE`
6. Išsaugo `run_manifest.json` su vykdymo statusu ir statistika (žr.
   `docs/architecture.md` "Run Manifest" - paaiškina, kodėl paleidimas baigėsi
   taip, kaip baigėsi) ir grąžina atitinkamą exit code operacinei sistemai/CI

## Circuit breaker ir structured logging

**Circuit breaker** (`circuit_breaker.py`, būsena `circuit_breaker_state.json`):
jei šaltinis fail'ina 3 paleidimus iš eilės, jis automatiškai "atidaromas"
(praleidžiamas be jokio bandymo) 24 valandoms - apsauga nuo beprasmio
pakartotinio bandymo su akivaizdžiai sugedusiu selektoriumi/URL. Po cooldown
periodo automatiškai bandoma vėl (half-open); jei pavyksta - grąžinama į
normalią (CLOSED) būseną.

**Structured logging** (`logging_config.py`): visi įvykiai logi'nami per
Python `logging`, ne `print()`. Formatas valdomas `LOG_FORMAT` kintamuoju:
```bash
python main.py                    # numatyta: žmogui skaitomas console formatas
LOG_FORMAT=json python main.py    # JSON eilutės - lengva grep/jq analizei
```
GitHub Actions workflow'e numatytas `LOG_FORMAT=json`, kad Actions logai būtų
lengviau analizuojami (pvz., `jq 'select(.level=="ERROR")'`).

## Automatinis paleidimas kasdien (lokaliai)

**Linux/Mac (cron):**
```bash
crontab -e
# Pridėkite eilutę (paleis kasdien 8:00):
0 8 * * * cd /kelias/iki/job_agent && /usr/bin/python3 main.py >> log.txt 2>&1
```

**Windows (Task Scheduler):**
Sukurkite naują užduotį, kuri paleidžia `python main.py` iš `job_agent` katalogo.

## Automatinis paleidimas per GitHub Actions — viešas repo, privatūs duomenys

Failas `.github/workflows/job-search.yml` jau paruoštas. Jūsų kodas gali būti
viešas (portfolio), o asmeniniai duomenys lieka GitHub Secrets — jų reikšmės
niekada nerodomos loguose net viešame repo (GitHub automatiškai jas paslepia
žvaigždutėmis `***`, jei kur nors pasirodytų).

1. **Sukurkite GitHub repozitoriją** (public — tinka portfolio, nemokama ir
   be minučių limito)

2. **Įkelkite projekto failus** (patikrinkite, kad `.env` NĖRA tarp jų — jis
   turi likti tik jūsų kompiuteryje):
   ```bash
   cd job_agent
   git init
   git add .
   git status   # patikrinkite, kad .env sąraše NĖRA
   git commit -m "Pradinė versija"
   git branch -M main
   git remote add origin https://github.com/forevercornix/job-agent.git
   git push -u origin main
   ```
   **Pastaba**: prieš viešą publikavimą suskaidykite šį commit'ą į logišką
   istoriją (žr. pagrindinį README "prieš publikuojant" checklist'ą).

3. **Pridėkite 4 pagrindinius Secrets** (Settings → Secrets and variables → Actions →
   "New repository secret"):
   | Name | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | jūsų Anthropic API raktas |
   | `SEARCH_KEYWORDS` | pvz. `projektu vadovas,IT projektu vadovas,product owner` |
   | `CANDIDATE_PROFILE` | jūsų CV santrauka (laisvas tekstas) |
   | `MIN_MATCH_SCORE` | pvz. `7` |

   (Jei norite gauti rezultatus el. paštu, žr. skyrių žemiau dėl dar 5 Secrets.)

4. **Įjunkite Actions**, jei reikia (Actions skirtukas → "I understand my
   workflows, go ahead and enable them")

5. **Pirmas paleidimas rankiniu būdu**: Actions → "Darbo paieškos agentas" →
   "Run workflow". Patikrinkite logus — jei selektoriai neveikia, pataisykite
   `scraper.py` lokaliai, commit'inkite (be `.env`!), bandykite vėl

6. **Grafikas**: `cron: "0 6 * * *"` (kasdien ~6:00 UTC) — pakeičiama
   `.github/workflows/job-search.yml` faile (crontab.guru padės su sintakse)

7. **Rezultatai**: `matched_jobs.json` matomas kaip "Artifact" prie kiekvieno
   paleidimo Actions skirtuke. `seen_jobs.json` išsaugomas per `actions/cache`
   tarp paleidimų (NE per git commit — taip jis niekada nepatenka į viešą git
   istoriją).

### ⚠️ Svarbi pastaba dėl artefaktų viešame repo

GitHub taisyklė: artefaktus gali atsisiųsti bet kas, turintis skaitymo teisę
repo — o viešame repo skaitymo teisę turi **visi prisijungę GitHub vartotojai**.
Jei siunčiate rezultatus el. paštu (žr. žemiau), artefaktas nebūtinas ir jį
galite pašalinti iš workflow.

## Rezultatų siuntimas sau el. paštu (privatu, be artefaktų)

Workflow'e jau yra paruoštas žingsnis, kuris siunčia el. laišką su rasta atitikimų
santrauka — jis suveikia tik jei rasta bent vienas tinkamas skelbimas.

### Reikalingi papildomi Secrets

| Name | Reikšmė (Gmail pavyzdys) |
|---|---|
| `MAIL_SERVER` | `smtp.gmail.com` |
| `MAIL_PORT` | `587` |
| `MAIL_USERNAME` | jūsų pilnas Gmail adresas |
| `MAIL_PASSWORD` | **App Password** (žr. žemiau — NE jūsų įprastas Gmail slaptažodis) |
| `MAIL_TO` | el. paštas, į kurį norite gauti rezultatus (gali būti tas pats) |

### Kaip susikurti Gmail App Password

Gmail nebeleidžia SMTP prisijungimo su įprastu slaptažodžiu, jei įjungtas 2FA
(o be 2FA App Password sukurti negalima — teks jį įjungti):

1. Įjunkite 2-Step Verification: myaccount.google.com/security
2. Eikite į myaccount.google.com/apppasswords
3. Sukurkite naują App Password (pavadinimą galite rašyti bet kokį, pvz. "job-agent")
4. Google sugeneruos 16 simbolių slaptažodį — jį ir įrašykite kaip `MAIL_PASSWORD` Secret

Kitiems paštams (Outlook, Yahoo ir pan.) principas panašus — reikės rasti
"App Password" arba "SMTP" nustatymus atitinkamo paslaugų teikėjo saugumo
skiltyje; serveris/prievadas bus kitokie (pvz. Outlook: `smtp.office365.com`, `587`).

### Kaip tai veikia

1. `main.py` sugeneruoja `matched_jobs.json`
2. `format_email.py` paverčia jį skaitomu tekstu (`email_body.txt`)
3. Jei rasta bent vienas tinkamas skelbimas, `dawidd6/action-send-mail` išsiunčia
   laišką per jūsų SMTP serverį į `MAIL_TO` adresą
4. Jei tinkamų skelbimų nerasta, laiškas nesiunčiamas (tuščias `email_body.txt`)

## Realių šaltinių naudojimas (lokaliai ir GitHub Actions)

Viešas `sources.yaml` naudoja generinius demo pavadinimus (žr. `SECURITY.md`
skyrių "Realių šaltinių pavadinimų privatumas" - tai sąmoningas pasirinkimas,
ne trūkumas). Norėdami naudoti realius šaltinius:

**Lokaliai** — žr. `docs/setup.md`.

**GitHub Actions:**
1. Sukurkite `SOURCES_LOCAL_YAML` Secret, kurio reikšmė — visas
   `sources.local.yaml` failo turinys (daugiaeilis YAML tekstas, įklijuotas
   tiesiai į Secret reikšmės lauką)
2. Workflow'e jau yra žingsnis "Atkurti privačius šaltinius (sources.local.yaml)
   iš Secret", kuris jį atkuria prieš paleidžiant `main.py`
3. Jei šio Secret nenustatysite, workflow tiesiog naudos viešą generinį
   `sources.yaml` (demo šaltinius) — klaidos nebus

**Prieš pridedami realų šaltinį, būtinai patikrinkite jo `robots.txt` ir
Paslaugų teikimo sąlygas** — žr. `SECURITY.md` skyrių "Web scraping ribos".
