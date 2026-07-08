# Repo peržiūra be realaus paleidimo (examples/)

Jei norite suprasti, kaip atrodo įėjimo/išėjimo duomenys nepaleidus scraperio
ar nenaudojant Claude API rakto, žr. `examples/`:
- `generic_job_list.html` — pavyzdinis HTML puslapis, kurį naršytų `scraper.py`
- `scraped_jobs.example.json` — pavyzdys, ką grąžina `scraper.py` prieš vertinimą
- `matched_jobs.example.json` — pavyzdys, ką grąžina `ranker.py` po vertinimo
- `email_preview.example.html` — pavyzdinis HTML laiškas (sugeneruotas realia
  `format_email.format_email_body_html()` funkcija iš duomenų aukščiau)

Papildomai — `eval/` kataloge yra didesnis (20 skelbimų) rankiniu būdu
pažymėtas duomenų rinkinys, naudojamas AI vertinimo tikslumui matuoti, ne tik
demonstracijai. Žr. `docs/llm-reliability.md` skyrių "Eval harness".
