"""
Paverčia matched_jobs.json į skaitomą el. laiško tekstą (email_body.txt).
Naudojama prieš siunčiant el. laišką GitHub Actions workflow'e.
"""

import html
import json
import os
from datetime import datetime
from urllib.parse import urlparse

import config


def format_email_body():
    if not os.path.exists(config.OUTPUT_FILE):
        return None  # nėra ką siųsti

    with open(config.OUTPUT_FILE, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    if not jobs:
        return None  # tinkamų skelbimų nerasta - laiško nesiunčiame

    lines = [
        f"Darbo paieškos agentas | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Rasta {len(jobs)} tinkamų skelbimų (balas >= {config.MIN_MATCH_SCORE}):",
        "",
    ]

    for job in jobs:
        lines.append(f"[{job['match_score']}/10] {job['title']}")
        lines.append(f"  Įmonė: {job['company']} | Šaltinis: {job['source']}")
        lines.append(f"  Nuoroda: {job['url']}")
        lines.append(f"  Kodėl tinka: {job['match_reason']}")
        evidence = job.get("match_evidence")
        if evidence:
            lines.append(f"  Pagrindimas: {evidence}")
        lines.append("")

    return "\n".join(lines)


def _safe_url(url: str) -> str:
    """
    Validuoja URL prieš įterpiant į HTML `href` atributą.

    SAUGUMAS: job['url'] kilęs iš scraped (trečiosios šalies) turinio -
    be šios patikros, kažkas galėtų sukurti skelbimą su url="javascript:alert(1)"
    ir tai taptų vykdomu kodu HTML laiške. Priimame TIK http/https schemas;
    kitaip grąžiname "#" (neaktyvi nuoroda) vietoj galimai pavojingo URL.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return html.escape(url, quote=True)
    except (ValueError, AttributeError):
        pass
    return "#"


def format_email_body_html(jobs=None):
    """
    HTML variantas - naudojamas portfolio demo/preview tikslais
    (žr. examples/email_preview.example.html). Realiame workflow pipeline
    šiuo metu naudojamas paprastas tekstinis variantas (format_email_body),
    bet ši funkcija leidžia bet kada pereiti prie HTML laiškų nekeičiant
    duomenų struktūros.

    SAUGUMAS: visi laukai (title, company, source, match_reason) kilę iš
    scraped (trečiosios šalies) darbo skelbimų turinio arba Claude
    sugeneruoto teksto - jie HTML escape'inami prieš įterpiant į šabloną,
    kad išvengtume HTML/script injection, jei laiškas atidaromas HTML pašto
    kliente. `url` laukas papildomai validuojamas (žr. _safe_url) - priimamos
    tik http/https schemos.
    """
    if jobs is None:
        if not os.path.exists(config.OUTPUT_FILE):
            return None
        with open(config.OUTPUT_FILE, "r", encoding="utf-8") as f:
            jobs = json.load(f)

    if not jobs:
        return None

    rows = "\n".join(
        f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;color:#2c7a4b;">
            {html.escape(str(job['match_score']))}/10
          </td>
          <td style="padding:8px;border-bottom:1px solid #eee;">
            <a href="{_safe_url(job['url'])}" style="color:#1a5fb4;text-decoration:none;font-weight:bold;">
              {html.escape(str(job['title']))}
            </a><br/>
            <span style="color:#555;">{html.escape(str(job['company']))} &middot; {html.escape(str(job['source']))}</span><br/>
            <span style="color:#777;font-size:13px;">{html.escape(str(job['match_reason']))}</span>
            {f'<br/><span style="color:#999;font-size:12px;font-style:italic;">Pagrindimas: &laquo;{html.escape(str(job["match_evidence"]))}&raquo;</span>' if job.get("match_evidence") else ""}
          </td>
        </tr>"""
        for job in jobs
    )

    return f"""<!DOCTYPE html>
<html lang="lt">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;">
  <h2 style="color:#1a5fb4;">Darbo paieškos agentas</h2>
  <p>Rasta {len(jobs)} tinkamų skelbimų (balas &ge; {html.escape(str(config.MIN_MATCH_SCORE))}):</p>
  <table style="width:100%;border-collapse:collapse;">
    {rows}
  </table>
  <p style="color:#999;font-size:12px;margin-top:20px;">
    Sugeneruota automatiškai · {datetime.now().strftime('%Y-%m-%d %H:%M')}
  </p>
</body>
</html>"""


if __name__ == "__main__":
    body = format_email_body()
    if body:
        with open("email_body.txt", "w", encoding="utf-8") as f:
            f.write(body)
        print("email_body.txt paruoštas.")
    else:
        # Tuščias failas signalizuoja workflow'ui, kad laiško siųsti nereikia
        with open("email_body.txt", "w", encoding="utf-8") as f:
            f.write("")
        print("Tinkamų skelbimų nerasta - laiško turinys tuščias.")
