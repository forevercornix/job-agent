"""
Testai schemas/rank_result.schema.json kontraktui - patikrina, kad:
1. Schema failas pats yra validus JSON Schema
2. Realūs ranker.score_job() rezultatai (sėkmės IR klaidų atvejais) ATITINKA
   šią schemą - t.y. dokumentacija ir kodas nesiskiria
3. Sąmoningai sugadintas rezultatas TEISINGAI atmetamas kaip nevalidus
"""

import json

import jsonschema
import pytest
from thinharness import HarnessError, ModelTurn

import ranker
from tests.scripted_model import ScriptedModel


def test_schema_file_is_valid_json_schema():
    """Pati schema turi būti sintaksiškai validus JSON Schema (draft-07)."""
    jsonschema.Draft7Validator.check_schema(ranker.RANK_RESULT_SCHEMA)


def test_error_result_conforms_to_contract():
    """_error_result() (naudojamas visuose klaidų keliuose) turi atitikti kontraktą."""
    result = ranker._error_result("Vertinimo klaida: testas")
    jsonschema.validate(instance=result, schema=ranker.RANK_RESULT_SCHEMA)  # nemeta išimties


def test_valid_complete_result_conforms_to_contract():
    result = {
        "score": 8,
        "reason": "Gerai atitinka",
        "evidence": "citata iš skelbimo",
        "matched_requirements": ["SQL", "Agile"],
        "missing_requirements": ["Java"],
        "grounded": True,
    }
    jsonschema.validate(instance=result, schema=ranker.RANK_RESULT_SCHEMA)


def test_contract_rejects_missing_required_field():
    incomplete = {"score": 8, "reason": "...", "evidence": "..."}  # trūksta grounded ir kt.
    with pytest.raises(jsonschema.exceptions.ValidationError):
        jsonschema.validate(instance=incomplete, schema=ranker.RANK_RESULT_SCHEMA)


def test_contract_rejects_score_out_of_range():
    invalid = {
        "score": 15,  # už 0-10 ribų
        "reason": "...", "evidence": "...",
        "matched_requirements": [], "missing_requirements": [], "grounded": True,
    }
    with pytest.raises(jsonschema.exceptions.ValidationError):
        jsonschema.validate(instance=invalid, schema=ranker.RANK_RESULT_SCHEMA)


def test_contract_rejects_wrong_type_for_grounded():
    invalid = {
        "score": 8, "reason": "...", "evidence": "...",
        "matched_requirements": [], "missing_requirements": [],
        "grounded": "yes",  # turi būti bool, ne string
    }
    with pytest.raises(jsonschema.exceptions.ValidationError):
        jsonschema.validate(instance=invalid, schema=ranker.RANK_RESULT_SCHEMA)


def test_contract_rejects_additional_unexpected_properties():
    """additionalProperties: false - schema griežtai riboja tik dokumentuotus laukus."""
    invalid = {
        "score": 8, "reason": "...", "evidence": "...",
        "matched_requirements": [], "missing_requirements": [], "grounded": True,
        "unexpected_field": "kažkas",
    }
    with pytest.raises(jsonschema.exceptions.ValidationError):
        jsonschema.validate(instance=invalid, schema=ranker.RANK_RESULT_SCHEMA)


def test_validate_against_contract_helper_accepts_valid_result():
    result = {
        "score": 7, "reason": "...", "evidence": "...",
        "matched_requirements": [], "missing_requirements": [], "grounded": True,
    }
    is_valid, error = ranker._validate_against_contract(result)
    assert is_valid is True
    assert error is None


def test_validate_against_contract_helper_rejects_invalid_result():
    invalid = {"score": 7}  # trūksta beveik visko
    is_valid, error = ranker._validate_against_contract(invalid)
    assert is_valid is False
    assert error is not None


# --- End-to-end through real ThinHarness + scripted Model ------------------


def _turn(score, evidence):
    return ModelTurn(text=json.dumps({
        "score": score,
        "reason": "Atitinka.",
        "evidence": evidence,
        "matched_requirements": ["SQL"],
        "missing_requirements": [],
    }))


def test_score_job_real_output_conforms_to_contract():
    model = ScriptedModel([_turn(8, "Reikalaujama SQL patirties")])
    job = {"title": "PM", "company": "Test", "snippet": "Reikalaujama SQL patirties."}

    result, _ = ranker.score_job(job, candidate_profile="test profile", model=model)

    jsonschema.validate(instance=result, schema=ranker.RANK_RESULT_SCHEMA)


def test_score_job_error_path_output_conforms_to_contract():
    model = ScriptedModel([HarnessError("provider error 401: invalid key")])
    job = {"title": "X", "company": "Y", "snippet": "..."}

    result, _ = ranker.score_job(job, candidate_profile="test profile", model=model)

    jsonschema.validate(instance=result, schema=ranker.RANK_RESULT_SCHEMA)


def test_evidence_contract_preserves_grounded_score_and_downgrades_fabrication():
    job_text = "Reikalaujama 5 metų Python programavimo patirties."
    job = {"title": "Developer", "company": "TestCo", "snippet": job_text}
    model = ScriptedModel(
        [_turn(8, "5 metų Python programavimo patirties")],
        [_turn(8, "10 metų kvantinės kriptografijos patirties")],
    )

    grounded, _ = ranker.score_job(job, candidate_profile="test", model=model)
    ungrounded, _ = ranker.score_job(job, candidate_profile="test", model=model)

    assert grounded["grounded"] is True
    assert grounded["score"] == 8
    assert ungrounded["grounded"] is False
    assert ungrounded["score"] == ranker.DOWNGRADE_SCORE_CAP
