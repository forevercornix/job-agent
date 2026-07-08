# Kandidato profilio šablonas

Tai šablonas, kaip suformuluoti `CANDIDATE_PROFILE` (žr. `.env.example`).
Šiame repo esantis pavyzdys yra generinis — realų savo profilį laikykite
tik lokaliame `.env` faile arba GitHub Secrets, niekada commit'inamame kode.

## Struktūra, kuri veikia geriausiai

```
<Vardas / rolė viena eilute>
<X+ metų patirtis>: <3-5 pagrindinės kompetencijos, atskirtos kableliais>.
Ieško: <norimos pozicijos>, <lokacija/nuotolinis>, <atlyginimo intervalas, jei aktualu>.
```

## Pavyzdys (generinis, be realių duomenų)

```
Vardas Pavardė - IT projektų vadovas / Product Owner
10+ metų patirtis: DVS/ERP/CRM diegimas, procesų skaitmenizacija, Agile/Scrum,
SQL, IT valdymas.
Ieško: IT projektų vadovo arba Product Owner pozicijų Vilniuje arba nuotoliniu
būdu, atlyginimas nuo X EUR/mėn.
```

## Kodėl trumpas profilis, o ne pilnas CV

- Claude API kaina auga su token kiekiu — trumpas, tikslus profilis pigesnis
  vertinant dešimtis skelbimų per dieną
- Trumpas profilis priverčia aiškiai suformuluoti prioritetus (rolė, patirtis,
  lokacija), o ne tikėtis, kad modelis pats išsirinks svarbiausią informaciją
  iš ilgo CV teksto
- Jei norite detalesnio vertinimo (pvz., pagal konkrečius įgūdžius), verta
  pereiti prie svertinio scoring (žr. `docs/scoring.md`) su struktūruotu
  profiliu (sąrašas įgūdžių + jų svarba), o ne vienu laisvo teksto lauku
