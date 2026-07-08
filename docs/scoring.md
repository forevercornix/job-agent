# Vertinimo metodika (Scoring)

## Dabartinė versija: vienas bendras balas

Šiuo metu `ranker.py` prašo Claude grąžinti **vieną** bendrą 1–10 balą kiekvienam
skelbimui, remiantis laisvo teksto kandidato profiliu (žr. `prompts/ranking_prompt.md`).
Tai paprasčiausias variantas, ir modeliui paliekama nuspręsti, kaip suderinti
skirtingus atitikimo aspektus.

## Rekomenduojama svertinė schema (patobulinimas, dar neįgyvendinta kode)

Jei norite skaidresnio, labiau kontroliuojamo vertinimo, verta pereiti prie
svertinio balo iš kelių atskirų komponentų:

| Kriterijus | Svoris | Ką matuoja |
|---|---|---|
| Role fit (pareigų atitikimas) | 30% | Ar skelbimo pavadinimas/aprašymas atitinka norimą rolę (pvz., "Project Manager" vs "Sales Manager") |
| Seniority (lygis) | 20% | Ar reikalaujama patirtis atitinka kandidato lygį (junior/mid/senior atitikimas) |
| Domain (sritis/pramonė) | 20% | Ar įmonės sritis/produktas atitinka kandidato patirties sritį (pvz., viešasis sektorius, SaaS, gamyba) |
| Technical match (techninės kompetencijos) | 15% | Ar reikalaujami įrankiai/technologijos (SQL, Agile, ERP ir pan.) sutampa su profiliu |
| Salary/Location (atlyginimas/lokacija) | 15% | Ar atitinka geografiją (Vilnius/nuotoliniu) ir atlyginimo intervalą, jei nurodyta skelbime |

**Bendras balas** = 0.30×role_fit + 0.20×seniority + 0.20×domain + 0.15×technical_match + 0.15×salary_location

Kiekvienas komponentas vertinamas atskirai 0–10 skalėje.

## Kaip tai įgyvendinti

1. Pakeisti `prompts/ranking_prompt.md`, kad Claude grąžintų JSON su atskirais
   laukais: `{"role_fit": 8, "seniority": 7, "domain": 9, "technical_match": 6,
   "salary_location": 10, "reason": "..."}`
2. `ranker.py` funkcijoje `score_job` apskaičiuoti svertinę sumą pagal lentelę
   aukščiau, o ne naudoti modelio grąžintą vieną skaičių tiesiogiai
3. Svorius laikyti `config.py` konstantomis, kad būtų lengva koreguoti be
   prompt'o keitimo

## Kodėl tai naudinga

- **Skaidrumas**: matote, *kodėl* skelbimas gavo tokį balą, ne tik galutinį skaičių
- **Konfigūruojama**: jei atlyginimas jums nesvarbus, sumažinate jo svorį iki 0%
  nekeisdami prompt'o
- **Stabilumas**: atskiri, siauri klausimai modeliui paprastai duoda nuoseklesnius
  atsakymus nei vienas platus "įvertink bendrai" klausimas
