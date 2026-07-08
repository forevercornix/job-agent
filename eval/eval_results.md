# Eval rezultatai

> ⚠️ **MOCK REŽIMAS** - šie rezultatai sugeneruoti PAPRASTA raktažodžių euristika, NE realiu Claude API (nebuvo prieinamas ANTHROPIC_API_KEY šio paleidimo metu). Tai demonstruoja, kad eval harness veikia (duomenys → vertinimas → metrikos → ataskaita), bet NEPARODO realaus LLM tikslumo. Paleiskite `python eval/run_eval.py` su nustatytu ANTHROPIC_API_KEY realiems rezultatams.

Sugeneruota: 2026-07-07T04:34:43.355536+00:00

**Bendras tikslumas (accuracy): 15/20 = 75.0%**

## Confusion Matrix

| Tikra \ Prognozė | match | maybe | no_match |
|---|---|---|---|
| **match** | 7 | 0 | 0 |
| **maybe** | 3 | 2 | 1 |
| **no_match** | 0 | 1 | 6 |

## Precision pagal klasę

| Klasė | Precision | TP | FP |
|---|---|---|---|
| match | 70.0% | 7 | 3 |
| maybe | 66.7% | 2 | 1 |
| no_match | 85.7% | 6 | 1 |

**Klaidingi teigiami 'match' atvejai (false positives): 3**

## Detalūs rezultatai

| ID | Pavadinimas | Balas | Tikra | Prognozė | OK? |
|---|---|---|---|---|---|
| 1 | IT Project Manager (ERP Implementation) | 10 | match | match | ✅ |
| 2 | Product Owner - SaaS Platform | 7 | match | match | ✅ |
| 3 | Digital Transformation Manager | 10 | match | match | ✅ |
| 4 | IT Program Manager - CRM Rollout | 10 | match | match | ✅ |
| 5 | Senior Project Manager - Public Informat | 10 | match | match | ✅ |
| 6 | Product Owner - Agile Team | 7 | match | match | ✅ |
| 7 | IT Delivery Manager | 10 | match | match | ✅ |
| 8 | Junior Project Coordinator | 6 | maybe | maybe | ✅ |
| 9 | Business Analyst | 4 | maybe | maybe | ✅ |
| 10 | Scrum Master | 10 | maybe | match | ❌ |
| 11 | IT Infrastructure Manager | 8 | maybe | match | ❌ |
| 12 | Marketing Project Manager | 10 | maybe | match | ❌ |
| 13 | Product Manager (not Owner) | 0 | maybe | no_match | ❌ |
| 14 | Sales Representative | 0 | no_match | no_match | ✅ |
| 15 | Warehouse Logistics Coordinator | 0 | no_match | no_match | ✅ |
| 16 | Graphic Designer | 0 | no_match | no_match | ✅ |
| 17 | HR Recruiter | 0 | no_match | no_match | ✅ |
| 18 | Restaurant Manager | 4 | no_match | maybe | ❌ |
| 19 | Electrician | 0 | no_match | no_match | ✅ |
| 20 | Customer Support Agent | 2 | no_match | no_match | ✅ |
