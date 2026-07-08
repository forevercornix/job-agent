"""Testai eval/run_eval.py harness logikai (be realaus Claude API kvietimo)."""

import importlib.util
import json
import os

import pytest

_EVAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval")
_spec = importlib.util.spec_from_file_location("run_eval", os.path.join(_EVAL_DIR, "run_eval.py"))
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)


def test_score_to_label_thresholds():
    assert run_eval.score_to_label(10) == "match"
    assert run_eval.score_to_label(7) == "match"
    assert run_eval.score_to_label(6) == "maybe"
    assert run_eval.score_to_label(4) == "maybe"
    assert run_eval.score_to_label(3) == "no_match"
    assert run_eval.score_to_label(0) == "no_match"


def test_dataset_file_is_valid_and_has_expected_labels():
    with open(run_eval.DATASET_PATH, encoding="utf-8") as f:
        dataset = json.load(f)

    assert len(dataset) >= 15
    for entry in dataset:
        assert entry["expected_label"] in run_eval.LABELS
        assert "title" in entry
        assert "snippet" in entry


def test_dataset_has_reasonable_label_distribution():
    """Patikrina, kad dataset nėra iškreiptas į vieną klasę (bent po keletą kiekvienos)."""
    with open(run_eval.DATASET_PATH, encoding="utf-8") as f:
        dataset = json.load(f)

    counts = {label: 0 for label in run_eval.LABELS}
    for entry in dataset:
        counts[entry["expected_label"]] += 1

    for label, count in counts.items():
        assert count >= 3, f"Per mažai '{label}' pavyzdžių dataset'e ({count})"


def test_mock_score_is_deterministic():
    job = {"title": "IT Project Manager", "snippet": "Agile, SQL, ERP diegimas."}
    profile = "IT projektų vadovas su Agile, SQL, ERP patirtimi."

    result1 = run_eval._mock_score(job, profile)
    result2 = run_eval._mock_score(job, profile)

    assert result1["score"] == result2["score"]


def test_mock_score_conforms_to_rank_result_contract():
    """Net mock scorer rezultatas turi atitikti tą patį struktūrinį kontraktą kaip realus ranker."""
    import jsonschema

    import ranker

    job = {"title": "IT Project Manager", "snippet": "Agile, SQL patirtis."}
    profile = "IT PM"

    result = run_eval._mock_score(job, profile)
    jsonschema.validate(instance=result, schema=ranker.RANK_RESULT_SCHEMA)


def test_mock_score_scores_higher_for_relevant_job():
    profile = "IT projektų vadovas, Agile, SQL, ERP, Product Owner patirtis."
    relevant_job = {"title": "IT Project Manager", "snippet": "Reikalinga Agile, SQL, ERP patirtis, projektų vadovavimas."}
    irrelevant_job = {"title": "Electrician", "snippet": "Elektros instaliacijos darbai."}

    relevant_result = run_eval._mock_score(relevant_job, profile)
    irrelevant_result = run_eval._mock_score(irrelevant_job, profile)

    assert relevant_result["score"] > irrelevant_result["score"]


def test_run_with_mock_produces_results_file(tmp_path, monkeypatch):
    """Smoke testas: run(use_mock=True) turi sėkmingai sugeneruoti eval_results.md be klaidų."""
    monkeypatch.setattr(run_eval, "RESULTS_PATH", str(tmp_path / "eval_results.md"))

    run_eval.run(use_mock=True)

    assert (tmp_path / "eval_results.md").exists()
    content = (tmp_path / "eval_results.md").read_text(encoding="utf-8")
    assert "MOCK REŽIMAS" in content
    assert "Confusion Matrix" in content
    assert "Precision pagal klasę" in content


@pytest.mark.parametrize("score,expected", [(0, "no_match"), (3, "no_match"), (4, "maybe"), (6, "maybe"), (7, "match"), (10, "match")])
def test_score_to_label_boundary_values(score, expected):
    assert run_eval.score_to_label(score) == expected
