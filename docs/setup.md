# Setup (diegimas ir konfigūracija)

## 1. Diegimas

```bash
pip install -r requirements.txt
playwright install chromium
```

## 2. Konfigūracija (privatūs duomenys)

```bash
cp .env.example .env
```

Atsidarykite `.env` ir įrašykite savo tikrus duomenis:
- `ANTHROPIC_API_KEY` — jūsų Anthropic API raktas
- `SEARCH_KEYWORDS` — raktažodžiai paieškai (atskirti kableliu)
- `CANDIDATE_PROFILE` — jūsų CV santrauka
- `MIN_MATCH_SCORE` — nuo kiek balų (1–10) skelbimas laikomas verčiu dėmesio

`.env` failas yra `.gitignore` sąraše — jis niekada necommitinamas. Jei šio
failo nėra arba kintamieji nenustatyti, `config.py` naudoja bendrus pavyzdinius
duomenis (kad projektą galėtų paleisti bet kas, be jūsų asmeninės info).

## 3. SVARBU prieš pirmą paleidimą — patikrinkite selektorius

Svetainių HTML struktūra keičiasi, todėl generinis selektorius `scraper.py`
(`_extract_jobs_from_page`) yra pradinis spėjimas. Prieš paleisdami:

1. Naršyklėje atidarykite paieškos URL, sudarytą pagal `sources.yaml`/`sources.local.yaml`
   šabloną (pvz., `{base_url}{search_path}?{query_param}=projektu+vadovas`)
2. Paspauskite F12 → Inspect ant vieno skelbimo elemento sąraše
3. Patikrinkite, ar skelbimo nuorodos href atitinka `job_link_substring`
   reikšmę tam šaltiniui `sources.yaml`/`sources.local.yaml` (pvz., `/job/`).
   Jei struktūra kitokia, pakoreguokite `job_link_substring` arba, jei reikia
   labiau specifinės logikos, papildykite `_extract_jobs_from_page()` funkciją
   `scraper.py`

Tą patį pakartokite kiekvienam šaltiniui `sources.yaml`.

### Kaip pridėti naują darbo skelbimų svetainę

Kadangi `scraper.py` yra generinis (viena funkcija visiems šaltiniams),
naujam šaltiniui **Python kodo keisti nereikia** — tiesiog pridėkite naują
įrašą `sources.yaml`:

```yaml
sources:
  # ... esami šaltiniai ...
  - name: naujas-portalas.lt
    base_url: "https://www.naujas-portalas.lt"
    search_path: "/paieska"
    query_param: "q"
    job_link_substring: "/skelbimas/"
    notes: "Trumpas aprašymas."
```

Paleiskite `python main.py` — naujas šaltinis automatiškai įtraukiamas į
paiešką be jokių kitų pakeitimų.

## Realių šaltinių naudojimas (lokaliai)

Viešas `sources.yaml` naudoja generinius demo pavadinimus (žr. `SECURITY.md`
skyrių "Realių šaltinių pavadinimų privatumas" - tai sąmoningas pasirinkimas,
ne trūkumas). Norėdami naudoti realius šaltinius lokaliai:

```bash
cp sources.local.yaml.example sources.local.yaml
# redaguokite sources.local.yaml su realiais duomenimis
```
`sources.local.yaml` yra `.gitignore` sąraše — `scraper.py` automatiškai
naudos jį vietoj viešo `sources.yaml`, jei failas egzistuoja.

**Prieš pridedami realų šaltinį, būtinai patikrinkite jo `robots.txt` ir
Paslaugų teikimo sąlygas** — žr. `SECURITY.md` skyrių "Web scraping ribos".

Realių šaltinių naudojimui GitHub Actions žr. `docs/deployment.md`.
