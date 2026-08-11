# Ranking Prompt ir ThinHarness Agent Loop

`ranker.py` vertina darbo skelbimą per fresh ThinHarness 0.6.0 `Harness` ir Anthropic Claude. Tai nėra single-shot klasifikatorius: modelis gali paprašyti pilno puslapio teksto, kai ~500 simbolių snippet nepakanka.

## Įrankis: `get_full_job_description`

Kiekvienam darbui sukuriamas atskiras `ToolSpec` su tuščiu Pydantic argumentų modeliu. Handler closure uždaro tik programiškai iš scraperio gautą `job["url"]`:

```json
{
  "name": "get_full_job_description",
  "parameters": {
    "type": "object",
    "properties": {},
    "additionalProperties": false
  }
}
```

Provider schema draudžia papildomus laukus su `additionalProperties=false`. Runtime Pydantic parsing juos vis tiek ignoruoja gynybiškai. Todėl neatitinkantis tool call negali pakeisti URL. Handler visada kviečia `scraper.fetch_page_text(job_url)`.

Sėkmingai gautas tekstas pridedamas prie `seen_text`, naudojamo evidence grounding. Handler išimtį ThinHarness paverčia modelio matomu failed `ToolResult`; `tool_retries=0`, todėl įrankis automatiškai nekartojamas ir modelis gali užbaigti vertinimą pagal turimą snippet.

## Loop ir capacity

```text
1. Harness gauna system prompt + <candidate_profile> ir <untrusted_job_posting> user duomenis.
2. Claude arba kviečia get_full_job_description, arba pateikia galutinę structured output.
3. ThinHarness vykdo tool ir tęsia tą pačią modelio sesiją.
4. Anthropic native JSON Schema atsakymas validuojamas kaip RankResponse.
5. Netinkama išvestis gauna iki 2 corrective retry.
```

Kiekvieno darbo konfigūracija: `builtin_tools=[]`, `local_tracing=False`, `temperature=0`, `max_tokens=1024`, `request_retries=2`, `max_model_requests=5`, `max_tool_calls=3`, `output_retries=2`, `tool_retries=0`. Builtin filesystem tools išjungti, nes modelis gauna adversarial scraped tekstą; plaintext local tracing išjungtas, nes promptuose yra kandidato profilis.

Laikina provider klaida (connection/timeout, HTTP 408, 409, 425, 429 ar 5xx) gauna iki dviejų ThinHarness provider request retry tame pačiame pokalbyje. Auth, permission ir kitos non-retryable 4xx nekartojamos. Retry išlaiko tool rezultatus ir bendrą grounding būseną.

## Structured output ir galutinis kontraktas

`RankResponse` reikalauja:

- `score: int`
- netuščio `reason: str`
- `evidence: str` (gali būti tuščias)

`matched_requirements` ir `missing_requirements` įvestys sąmoningai permissive bei default'inamos į `[]`; `_coerce_string_list` po run'o išlaiko ankstesnį netvarkingų ir numerinių sąrašų apdorojimą. `score` po validacijos aplikacijoje apkarpomas į 0–10, kaip ir prieš migraciją. Galutinis dict dar kartą validuojamas prieš `schemas/rank_result.schema.json`.

## Grounding (Evidence)

System prompt reikalauja trumpos tiesioginės citatos. Aplikacija nepasitiki vien promptu: `_is_evidence_grounded` tikrina citatos egzistavimą visame modelio matytame tekste (title, company, snippet ir sėkmingi tool tekstai) per case-insensitive substring bei fuzzy match.

Jei citata tuščia arba nerandama, `grounded=False`, o balas apkarpomas iki `DOWNGRADE_SCORE_CAP` (3/10). Tai yra **evidence presence validation**, ne semantic entailment: tikra, bet sprendimui nereikšminga citata vis tiek gali praeiti.

## Prompt Injection

Apsauga išlieka defense-in-depth:

1. System instrukcijos atskirtos nuo user duomenų.
2. Kandidato profilis ir skelbimas pažymėti kaip nepatikimi duomenys; skelbimas apgaubtas `<untrusted_job_posting>`.
3. System prompt draudžia vykdyti instrukcijas iš profilio, snippet ar tool teksto.
4. Vienintelis custom tool neturi modelio valdomo URL; jokie builtin įrankiai neeksponuojami.
5. Tool/model capacity riboja pakartotinių veiksmų žalą.
6. Grounding ir score clamp vykdomi aplikacijoje nepriklausomai nuo modelio paklusimo.

Tai nėra absoliuti prompt-injection garantija. Agentas tik siūlo darbus, o galutinis sprendimas lieka žmogui.

## Determinizmas ir stebėsena

`temperature=0` mažina atsitiktinį balo svyravimą, bet negarantuoja identiškų atsakymų ar teisingo sprendimo. `score_job()` išlaiko `(result, stats)` kontraktą; `rank_jobs()` agreguoja modelio request, tool call ir ungrounded skaitiklius. Ranker logina tool fetch klaidos tipą ir structured-output retry skaičių. Jis nelogina prompto ar tool teksto. Provider transporto retry atskirai į usage nepatenka. Galutinai nepavykęs provider request aproksimuojamas kaip vienas request.

## Galimi patobulinimai

- semantinis evidence/reason pagrįstumo validatorius
- programinis matched/missing reikalavimų grounding
- svertinis vertinimas pagal kriterijus (`docs/scoring.md`)
- realus prieš/po eval su `ANTHROPIC_API_KEY`
- detalesnė per-turn telemetrija be jautraus promptų turinio saugojimo
