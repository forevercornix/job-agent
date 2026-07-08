# Žinomi apribojimai

Trumpa versija (4 svarbiausi punktai) yra pagrindiniame README. Čia — pilnas sąrašas.

- **Scraperiai gali lūžti**, kai svetainė pakeičia DOM/HTML struktūrą —
  generiniai selektoriai (`sources.yaml`/`sources.local.yaml`) veikia
  daugumai atvejų, bet nėra garantijos ilgalaikiam stabilumui be priežiūros
- Kai kurios svetainės gali rodyti CAPTCHA ar blokuoti per dažnas užklausas —
  script'as daro 2 sek. pauzę tarp užklausų, o laikinoms klaidoms (rate limit,
  tinklo triktys) automatiškai bando dar 2 kartus su eksponentiniu backoff
- LinkedIn ir panašios platformos su prisijungimo siena čia neįtrauktos —
  joms geriau tinka Claude in Chrome plėtinys su jūsų prisijungusia sesija
- Generinis selektorius (`job_link_substring`) veikia daugumai svetainių
  struktūrų, bet retkarčiais reikės pakoreguoti `sources.local.yaml` arba
  `_extract_jobs_from_page()`, kai svetainė keičia dizainą
- Retry logika taikoma tik laikinoms klaidoms (tinklas, rate limit, 5xx) —
  autentifikacijos ar blogos užklausos klaidos nekartojamos (nepavyktų ir kitą kartą)
- **LLM vertinimas nėra 100% deterministinis** — `temperature=0` sumažina
  atsitiktinį svyravimą, bet NEPAŠALINA jo visiškai ir NEPAGERINA sprendimo
  kokybės, tik nuoseklumą
- Prompt injection apsauga (žr. `prompts/ranking_prompt.md`) yra
  defense-in-depth, ne absoliuti garantija — labai sofistikuotas bandymas
  manipuliuoti tekste teoriškai vis tiek galėtų paveikti dalį atsakymo
  (nors ne galutinį balą, kuris apkarpomas kode)
- Eval harness (`eval/`) egzistuoja ir realiai paleistas, bet **šiame repo
  tik mock režimu** (be `ANTHROPIC_API_KEY`) - `eval/eval_results.md` rodo, kad
  pati sistema (dataset → vertinimas → metrikos → ataskaita) veikia, bet
  NEPARODO realaus Claude tikslumo. Paleiskite `python eval/run_eval.py` su
  tikru API raktu realiems precision/recall skaičiams
- `sources.yaml` (vieša versija) naudoja generinius demo pavadinimus; realiems
  šaltiniams reikia atskiro `sources.local.yaml` (žr. `docs/setup.md`) — tai
  sąmoningas privatumo pasirinkimas, ne trūkumas
- Run Manifest (`run_manifest.json`) fiksuoja statusą ir teisingą exit code,
  bet **neturi automatinio pranešimo** (Slack/Discord/SMS) kritinių klaidų
  atveju — GitHub Actions email pranešimas apie failed workflow suveiks
  (numatytasis GitHub elgesys), bet jei norite greitesnio/kito kanalo
  pranešimo, reikėtų pridėti papildomą workflow žingsnį
- **Šis įrankis NEPAKEIČIA žmogaus sprendimo** — jis tik siūlo ir surikiuoja
  kandidatus pagal atitikimą; jokia paraiška nesiunčiama automatiškai, ir
  galutinį sprendimą dėl kiekvieno skelbimo visada turėtų priimti žmogus
- **Būtina gerbti šaltinių Paslaugų teikimo sąlygas (ToS) ir `robots.txt`** —
  prieš pridedant realų šaltinį į `sources.local.yaml`, patikrinkite, ar
  automatizuotas naršymas leidžiamas (žr. `SECURITY.md`)

## Teisinė pastaba ir atsakingas naudojimas

Šis projektas skirtas **edukaciniams ir asmeninės darbo paieškos automatizavimo
tikslams** bei kaip portfolio pavyzdys. Naudodami jį:
- laikykitės atitinkamų svetainių `robots.txt` ir Paslaugų teikimo sąlygų
- nedidinkite užklausų dažnio be pagrindo (numatytoji konfigūracija — kartą per
  dieną su pertraukomis tarp užklausų)
- nenaudokite komerciniam duomenų rinkimui ar perpardavimui

Daugiau — žr. `SECURITY.md` skyrių "Web scraping ribos ir atsakingas naudojimas".
