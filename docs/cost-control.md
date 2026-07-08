# Cost Control - Claude API išlaidų valdymas

Keturi mechanizmai, ribojantys, kiek realiai kainuoja vienas paleidimas:

**1. Seen jobs praleidžiami PRIEŠ API kvietimą**
`deduplicator.deduplicate()` pašalina jau anksčiau matytus skelbimus
(`seen_jobs.json`) DAR PRIEŠ juos siunčiant Claude API - jau vertinti
skelbimai niekada nesiunčiami pakartotinai, nepriklausomai nuo to, kiek
kartų `scraper.py` juos vėl surastų.

**2. Max chars per skelbimą**
`scraper.fetch_page_text()` apkarpo bet kokį per `get_full_job_description`
įrankį gautą tekstą iki 3000 simbolių (`max_chars`), o pradinis anonsas
(`snippet`) - iki 500 simbolių jau scraping metu. Tai riboja, kiek tokenų
sunaudoja kiekvienas atskiras Claude kvietimas.

**3. Max jobs per run** (`config.MAX_JOBS_PER_RUN`, numatyta: 50)
Jei per vieną paleidimą surandama daugiau naujų skelbimų nei šis limitas
(pvz., pirmas paleidimas su daug istorinių duomenų), TIK pirmieji
`MAX_JOBS_PER_RUN` siunčiami Claude vertinimui - likusieji **lieka
"nematyti"** (`seen_urls` atnaujinamas TIK realiai įvertintiems) ir bus
pervertinti KITAME paleidime, o ne prarasti ar visi iškart nusiųsti Claude
per vieną paleidimą (žr. `tests/test_main_unit.py::test_main_caps_jobs_sent_to_ranker_per_max_jobs_per_run`).

**4. API kvietimai loginami manifeste**
Kiekvienas paleidimas fiksuoja `api_calls_made` ir `tool_calls_made`
`run_manifest.json` faile (žr. skyrių "Run Manifest" `docs/architecture.md`) -
matote TIKSLIAI, kiek kartų buvo kreiptasi į Claude API, be poreikio
skaičiuoti iš Anthropic Console atskirai.

**Ko tai NEIŠSPRENDŽIA**: nėra griežto piniginio biudžeto (pvz., "ne daugiau
kaip 1 USD per paleidimą") - visi keturi mechanizmai riboja KIEKĮ (skelbimų/
simbolių skaičių), o ne tiesiogiai dolerius, nes token'ų kaina priklauso nuo
konkretaus modelio ir gali keistis.
