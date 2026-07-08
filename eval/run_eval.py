"""
Eval harness: paleidžia ranker.score_job() prieš eval/dataset.json (rankiniu
būdu pažymėtus skelbimus su expected_label) ir apskaičiuoja tikslumo
metrikas (precision per klasę, false positives, overall accuracy).

NAUDOJIMAS SU REALIU CLAUDE API:
    export ANTHROPIC_API_KEY=jusu-raktas
    python eval/run_eval.py

NAUDOJIMAS BE API RAKTO (MOCK REŽIMAS):
    python eval/run_eval.py --mock
    (arba automatiškai persijungia į --mock, jei ANTHROPIC_API_KEY nenustatytas)

MOCK REŽIMAS naudoja paprastą raktažodžių persidengimo euristiką VIETOJ
realaus Claude API - tai NĖRA tikras LLM vertinimas, o tik demonstracija,
kad eval harness (duomenų įkėlimas, metrikų skaičiavimas, ataskaitos
generavimas) REALIAI VEIKIA IR PALEISTA. Realiam tikslumo įvertinimui
būtina paleisti su tikru ANTHROPIC_API_KEY.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(EVAL_DIR, "dataset.json")
PROFILE_PATH = os.path.join(EVAL_DIR, "candidate_profile.txt")
RESULTS_PATH = os.path.join(EVAL_DIR, "eval_results.md")

LABELS = ("match", "maybe", "no_match")


def score_to_label(score: int) -> str:
    if score >= 7:
        return "match"
    if score >= 4:
        return "maybe"
    return "no_match"


def _mock_score(job: dict, profile: str) -> dict:
    """
    Paprasta raktažodžių persidengimo euristika - NAUDOJAMA TIK kai
    ANTHROPIC_API_KEY nenustatytas, kad harness'ą būtų galima demonstruoti
    be realaus API rakto. Tai NĖRA LLM vertinimas.
    """
    text = f"{job['title']} {job['snippet']}".lower()
    profile_lower = profile.lower()

    keywords = ["projekt", "product owner", "agile", "scrum", "erp", "crm", "sql",
                "prince2", "bpmn", "it ", "digital transformation", "program manager",
                "delivery manager", "vadovas", "vadov", "backlog", "roadmap"]
    hits = sum(1 for kw in keywords if kw in text and kw in profile_lower)
    strong_hits = sum(1 for kw in ["product owner", "project manager", "projektų vadovas",
                                    "program manager", "delivery manager", "digital transformation"]
                       if kw in text)

    score = min(10, hits * 2 + strong_hits * 3)
    return {
        "score": score,
        "reason": f"[MOCK] {hits} raktažodžių sutapimų, {strong_hits} stiprių sutapimų",
        "evidence": "",
        "matched_requirements": [],
        "missing_requirements": [],
        "grounded": False,
    }


def run(use_mock: bool) -> None:
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        profile = f.read().strip()

    if not use_mock:
        import ranker
        ok, err = ranker.preflight_check()
        if not ok:
            print(f"KLAIDA: Claude API nepasiekiamas ({err}). Naudokite --mock arba nustatykite ANTHROPIC_API_KEY.")
            sys.exit(1)

    rows = []
    confusion = {actual: {predicted: 0 for predicted in LABELS} for actual in LABELS}

    for entry in dataset:
        job = {"title": entry["title"], "company": entry["company"],
               "snippet": entry["snippet"], "url": entry["url"], "source": "eval"}

        if use_mock:
            result = _mock_score(job, profile)
        else:
            import ranker
            result, _ = ranker.score_job(job, profile)

        predicted_label = score_to_label(result["score"])
        expected_label = entry["expected_label"]
        confusion[expected_label][predicted_label] += 1

        rows.append({
            "id": entry["id"], "title": entry["title"], "score": result["score"],
            "expected": expected_label, "predicted": predicted_label,
            "correct": predicted_label == expected_label,
        })

    _write_report(rows, confusion, use_mock)


def _write_report(rows: list, confusion: dict, use_mock: bool) -> None:
    total = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    accuracy = correct / total if total else 0.0

    lines = ["# Eval rezultatai\n"]
    if use_mock:
        lines.append(
            "> ⚠️ **MOCK REŽIMAS** - šie rezultatai sugeneruoti PAPRASTA "
            "raktažodžių euristika, NE realiu Claude API (nebuvo prieinamas "
            "ANTHROPIC_API_KEY šio paleidimo metu). Tai demonstruoja, kad "
            "eval harness veikia (duomenys → vertinimas → metrikos → ataskaita), "
            "bet NEPARODO realaus LLM tikslumo. Paleiskite `python eval/run_eval.py` "
            "su nustatytu ANTHROPIC_API_KEY realiems rezultatams.\n"
        )
    lines.append(f"Sugeneruota: {datetime.now(timezone.utc).isoformat()}\n")
    lines.append(f"**Bendras tikslumas (accuracy): {correct}/{total} = {accuracy:.1%}**\n")

    lines.append("## Confusion Matrix\n")
    lines.append("| Tikra \\ Prognozė | match | maybe | no_match |")
    lines.append("|---|---|---|---|")
    for actual in LABELS:
        row = confusion[actual]
        lines.append(f"| **{actual}** | {row['match']} | {row['maybe']} | {row['no_match']} |")
    lines.append("")

    lines.append("## Precision pagal klasę\n")
    lines.append("| Klasė | Precision | TP | FP |")
    lines.append("|---|---|---|---|")
    for label in LABELS:
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in LABELS if other != label)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        lines.append(f"| {label} | {precision:.1%} | {tp} | {fp} |")
    lines.append("")

    false_positives_match = sum(
        1 for r in rows if r["predicted"] == "match" and r["expected"] != "match"
    )
    lines.append(f"**Klaidingi teigiami 'match' atvejai (false positives): {false_positives_match}**\n")

    lines.append("## Detalūs rezultatai\n")
    lines.append("| ID | Pavadinimas | Balas | Tikra | Prognozė | OK? |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        mark = "✅" if r["correct"] else "❌"
        lines.append(f"| {r['id']} | {r['title'][:40]} | {r['score']} | {r['expected']} | {r['predicted']} | {mark} |")

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Rezultatai išsaugoti: {RESULTS_PATH}")
    print(f"Accuracy: {accuracy:.1%} ({correct}/{total})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Eval harness ranker.py tikslumui matuoti")
    parser.add_argument("--mock", action="store_true", help="Naudoti mock scorer vietoj realaus Claude API")
    args = parser.parse_args()

    mock_mode = args.mock or not os.environ.get("ANTHROPIC_API_KEY")
    if mock_mode and not args.mock:
        print("ANTHROPIC_API_KEY nenustatytas - automatiškai persijungiama į --mock režimą.")

    run(use_mock=mock_mode)
