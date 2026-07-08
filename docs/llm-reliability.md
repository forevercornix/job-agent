# LLM Reliability - kaip valdomas AI vertinimo patikimumas

**Dažnas klausimas apie AI agentus: "kaip valdai hallucinations?"** Trumpas
sąžiningas atsakymas: promptu jų "uždrausti" negalima - reikia struktūrinių
apsaugų, kurios veikia NEPRIKLAUSOMAI nuo to, ar modelis "pakluso"
instrukcijai. Šis projektas taiko kelis sluoksnius, veikiančius kartu:

**1. Struktūrizuotas JSON išvesties formatas**
Claude visada privalo grąžinti fiksuotos struktūros JSON:
```json
{"score": 1-10, "reason": "...", "evidence": "...",
 "matched_requirements": [...], "missing_requirements": [...]}
```
Ne laisvo teksto atsakymas, kurį reikėtų interpretuoti - griežta struktūra
leidžia programiškai validuoti kiekvieną atsakymo dalį (žr. punktą 2 žemiau).

**2. JSON Schema validacija (dviguba)**
- **Kodinė validacija** (`ranker._validate_schema`) - kiekvienas PRADINIS
  modelio atsakymas tikrinamas, ar turi VISUS privalomus laukus (`score`,
  `reason`, `evidence`) teisingais tipais. Jei modelis praleidžia lauką ar
  grąžina netinkamą tipą → **schema validation failure** (klaida, `score=0`).
- **Formalus kontraktas** (`schemas/rank_result.schema.json`, JSON Schema
  draft-07) - GALUTINIS (po apdorojimo) rezultatas papildomai validuojamas
  per `jsonschema` biblioteką prieš `ranker._validate_against_contract()`.
  Tai atskiras, versijuojamas dokumentas - "source of truth" modelio
  atsakymo struktūrai, kurio atitikimą realiai patikrina
  `tests/test_schema_contract.py` (12 testų).

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

Konkretus scenarijus (aukštas balas + nepagrįsta citata):
```python
# Modelis grąžina: {"score": 9, "reason": "Puikiai tinka!",
#                    "evidence": "Reikalaujama 15 metų branduolinės inžinerijos patirties"}
# Realiame skelbime apie tai NIEKUR neužsimenama.
#
# Rezultatas PO validacijos: score <= 3, grounded=False
# (žr. tests/test_ranker.py::test_score_job_downgrades_high_score_with_fabricated_evidence)
```

**5. Fallback ant nevalidaus atsakymo**
Kiekvienas galimas nesėkmės taškas (API klaida, JSON parse klaida, schema
validacijos klaida, agent loop iteracijų limitas) grąžina VIENODOS
struktūros saugų rezultatą (`_error_result()`) - `score=0`, aiškus `reason`
su klaidos priežastimi. Joks blogas atsakymas nesustabdo viso proceso ar
nepalieka nenuspėjamos būsenos.

**6. Temperature=0**
Sumažina atsitiktinį balo svyravimą, jei tas pats skelbimas vertinamas
pakartotinai. **Svarbu suprasti ribą**: tai NEPAGERINA sprendimo kokybės,
tik nuoseklumą - modelis vis tiek gali klaidingai įvertinti atitikimą,
tiesiog darys tai nuosekliau.

**7. Testai promptų/išvesties kontraktui**
`tests/test_ranker_validation.py` (22 testai) tikrina PAČIAS validacijos
funkcijas izoliuotai: schema atmetimo atvejus, evidence substring/fuzzy
atpažinimą, fabrikuotos citatos atmetimą. `tests/test_ranker.py` turi
dedikuotą testą lygiai šiam scenarijui (aukštas balas + nepagrįsta
citata → downgrade).

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
