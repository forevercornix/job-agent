"""
Skelbimų dublikatų šalinimo logika.

Atsakomybė:
- pašalinti dublikatus tarp kelių paieškų (skirtingi raktažodžiai gali
  grąžinti tą patį skelbimą keliskart)
- atskirti jau anksčiau matytus skelbimus (tarp atskirų agento paleidimų)
- tvarkyti "matytų" skelbimų sąrašo failą (JSON su URL sąrašu)
"""

import json
import os


def load_seen_urls(path: str) -> set:
    """Įkelia anksčiau matytų skelbimų URL sąrašą. Grąžina tuščią set, jei failo nėra."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen_urls(path: str, urls) -> None:
    """Išsaugo matytų skelbimų URL sąrašą į JSON failą."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(urls), f, ensure_ascii=False, indent=2)


def deduplicate(jobs: list, seen_urls: set) -> list:
    """
    Pašalina dublikatus (pagal URL) tarp pačių `jobs` ir atmeta tuos,
    kurių URL jau yra `seen_urls`.

    Grąžina sąrašą unikalių, dar nematytų skelbimų (tvarka išsaugota).
    """
    unique_new_jobs = {}
    for job in jobs:
        url = job.get("url")
        if not url:
            continue
        if url not in seen_urls and url not in unique_new_jobs:
            unique_new_jobs[url] = job
    return list(unique_new_jobs.values())
