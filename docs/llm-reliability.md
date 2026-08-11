# LLM Reliability - kaip valdomas AI vertinimo patikimumas

**Dažnas klausimas apie AI agentus: "kaip valdai hallucinations?"** Trumpas
sąžiningas atsakymas: promptu jų "uždrausti" negalima - reikia struktūrinių
apsaugų, kurios veikia NEPRIKLAUSOMAI nuo to, ar modelis "pakluso"
instrukcijai. Šis projektas taiko kelis sluoksnius, veikiančius kartu:

**1. Struktūrizuotas modelio išvesties formatas**
`ThinHarness 0.6.0` siunčia Anthropic native JSON Schema išvesties užklausą ir grąžina Pydantic validuotą `RankResponse`:
```json
{"score": 1-10, "reason": "...", "evidence": "...",
 "matched_requirements": [...], "missing_requirements": [...]}
```
Ne laisvo teksto atsakymas, kurį aplikacija pati parsina: `score`, netuščias
`reason` ir `evidence` validuojami per `RankResponse`. Netinkama išvestis gauna
iki dviejų ThinHarness corrective retry; tik išnaudojus juos grąžinamas saugus
`score=0`. `matched_requirements`/`missing_requirements` sąmoningai lieka
permissive ir po to tvarkomi `_coerce_string_list`, kad išliktų legacy elgesys.

**2. Struktūros validacija (dviguba)**
- **Modelio išvestis** (`ranker.RankResponse`) - privalomi laukai ir jų tipai
  validuojami ThinHarness structured-output cikle. Schema klaida dabar yra
  pataisoma modelio run'o viduje, o ne iškart paverčiama `score=0`.
- **Formalus kontraktas** (`schemas/rank_result.schema.json`, JSON Schema
  draft-07) - GALUTINIS (po apdorojimo) rezultatas papildomai validuojamas
  per `jsonschema` biblioteką prieš `ranker._validate_against_contract()`.
  Tai atskiras, versijuojamas dokumentas - "source of truth" modelio
  atsakymo struktūrai, kurio atitikimą realiai patikrina
  `tests/test_schema_contract.py`.

**3. Grounding (evidence) reikalavimas**
Kiekvienas balas privalo turėti `evidence` - trumpą (≤15 žodžių) TIESIOGINĘ
citatą iš skelbimo teksto, arba tuščią eilutę, jei nėra ką pacituoti.
**Bendros frazės be pagrindimo** (pvz., "Puikiai tinka" be citatos)
**neatitinka reikalavimo** ir apdorojamos kaip nepatikimas rezultatas (žr. 4).

**4. Programinis evidence groundedness patikrinimas** (`ranker._is_evidence_grounded`)
Tai svarbiausias sluoksnis: **neapsiribojama vien prašymu prompte** - kiekviena
`evidence` citata PROGRAMIŠKAI tikrinama, ar ji REALIAI yra skelbimo tekste
(exact substring match + fuzzy match per `difflib`, jei modelis šiek tiek
perfrazavo). Jei citata nerandama (modelis ją "sugalvojo" arba tiesiog
nepateikė) → **balas priverstinai nužeminamas** iki `DOWNGRADE_SCORE_CAP`
(numatyta: 3/10), **nepriklausomai nuo to, ką modelis parašė "reason" lauke**.

**TIKSLI TERMINOLOGIJA (svarbu neperdėti, ką ši patikra realiai garantuoja)**:
tai **"evidence PRESENCE validation"** (citatos EGZISTAVIMO patikra), o NE
**"semantic entailment validation"** (loginio pagrįstumo patikra). Konkrečiai:
- Patikra patvirtina, kad citata **egzistuoja** skelbimo tekste
- Patikra **NEPATVIRTINA**, kad citata yra **reikšminga** vertinimui, kad
  `reason` **logiškai išplaukia** iš citatos, ar kad citata **tikrai susijusi**
  su kandidato profiliu (modelis galėtų pacituoti tikrą, bet nereikšmingą
  frazę, ir vis tiek "pereiti" šią patikrą, jei citata pati savaime yra tekste)
- Fuzzy match (žr. `fuzzy_threshold=0.8`) reiškia, kad priimama ne tik
  TIKSLI citata, bet ir šiek tiek perfrazuota - tai sąmoningas kompromisas
  tarp griežtumo ir praktiškumo, ne absoliuti "tik pažodinė citata" garantija

Konkretus scenarijus (aukštas balas + nepagrįsta citata):
```python
# Modelis grąžina: {"score": 9, "reason": "Puikiai tinka!",
#                    "evidence": "Reikalaujama 15 metų branduolinės inžinerijos patirties"}
# Realiame skelbime apie tai NIEKUR neužsimenama.
#
# Rezultatas PO validacijos: score <= 3, grounded=False
# (žr. tests/test_ranker.py::test_fabricated_evidence_downgrades_high_score)
```

**5. Retry ir fallback**
Netinkama struktūrizuota išvestis taisoma iki dviejų kartų tame pačiame
ThinHarness run'e. Laikinos provider klaidos (connection/timeout, HTTP 408,
409, 425, 429 ar 5xx) gauna iki dviejų provider request retry tame pačiame
pokalbyje. Auth, permission ir kitos non-retryable 4xx nekartojamos. Jau užbaigtas scraping
įrankio kvietimas nekartojamas. Galutinė provider, output-validation ar capacity klaida vis tiek grąžina
vienodos struktūros `_error_result()` su `score=0` ir nesustabdo kitų darbų.

**6. Temperature=0**
Sumažina atsitiktinį balo svyravimą, jei tas pats skelbimas vertinamas
pakartotinai. **Svarbu suprasti ribą**: tai NEPAGERINA sprendimo kokybės,
tik nuoseklumą - modelis vis tiek gali klaidingai įvertinti atitikimą,
tiesiog darys tai nuosekliau.

**7. Testai promptų/išvesties kontraktui**
`tests/test_ranker_validation.py` tikrina `RankResponse`, evidence ir sąrašų
normalizavimo gryną logiką. `tests/test_ranker.py` leidžia realų ThinHarness
ciklą su scripted `Model`/`ModelSession` fake ir tikrina tool, SSRF,
structured-output retry, provider request retry, capacity, statistiką bei saugų
fallback - ne Anthropic SDK mock'o call seką.

**8. Eval harness** (`eval/`)
15-30 rankiniu būdu pažymėtų skelbimų (`eval/dataset.json`) su expected_label
(`match`/`maybe`/`no_match`). `eval/run_eval.py` paleidžia `ranker.score_job()`
prieš kiekvieną, skaičiuoja confusion matrix, precision per klasę, false
positives, ir generuoja `eval/eval_results.md`. **Sąžiningai**: šiame repo
esantis `eval_results.md` sugeneruotas MOCK režimu (be realaus API rakto) -
jis įrodo, kad harness veikia, bet neparodo realaus Claude tikslumo.
Paleiskite su tikru `ANTHROPIC_API_KEY` realiems skaičiams.

**Ko tai NEIŠSPRENDŽIA** (sąžiningai, ne nutylėta):
- `evidence` groundedness patikra sumažina, bet **nepašalina** rizikos -
  teoriškai fuzzy match galėtų klaidingai "priimti" citatą, kuri iš tikrųjų
  yra tik atsitiktinai panaši į realų tekstą (žr. `fuzzy_threshold=0.8`)
- Eval harness egzistuoja, bet šiame repo paleistas tik MOCK režimu (žr. 8) -
  realus tikslumas (precision/recall prieš žmogaus sprendimą) NEIŠMATUOTAS
- `matched_requirements`/`missing_requirements` laukai NĖRA programiškai
  tikrinami tuo pačiu grounding principu kaip `evidence` - tai žinoma
  asimetrija (žr. `prompts/ranking_prompt.md` "Galimi patobulinimai")

Pilnas techninis paaiškinimas: `prompts/ranking_prompt.md` skyriai "Grounding"
ir "Determinizmas".
