"""
Testai schemas/rank_result.schema.json kontraktui - patikrina, kad:
1. Schema failas pats yra validus JSON Schema
2. Realūs ranker.score_job() rezultatai (sėkmės IR klaidų atvejais) ATITINKA
   šią schemą - t.y. dokumentacija ir kodas nesiskiria
3. Sąmoningai sugadintas rezultatas TEISINGAI atmetamas kaip nevalidus
"""

from unittest.mock import patch

import jsonschema
import pytest

import ranker


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


# --- End-to-end: realus score_job() rezultatas per mock'intą Claude API ----

def _mock_text_response(text: str):
    from unittest.mock import MagicMock
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = text
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.stop_reason = "end_turn"
    return mock_response


@patch("ranker.client")
def test_score_job_real_output_conforms_to_contract(mock_client):
    """
    KRITINIS testas: realus (mock'intu API) score_job() rezultatas TURI
    atitikti formalų kontraktą - tai patvirtina, kad dokumentacija
    (schemas/rank_result.schema.json) ir kodo elgesys nesiskiria.
    """
    mock_client.messages.create.return_value = _mock_text_response(
        '{"score": 8, "reason": "Gerai atitinka.", '
        '"evidence": "Reikalaujama SQL patirties", '
        '"matched_requirements": ["SQL"], "missing_requirements": []}'
    )

    job = {"title": "PM", "company": "Test", "snippet": "Reikalaujama SQL patirties."}
    result, _ = ranker.score_job(job, candidate_profile="test profile")

    jsonschema.validate(instance=result, schema=ranker.RANK_RESULT_SCHEMA)  # nemeta išimties


@patch("ranker.client")
def test_score_job_error_path_output_conforms_to_contract(mock_client):
    """Klaidos kelio (API exception) rezultatas TAIP PAT turi atitikti kontraktą."""
    mock_client.messages.create.side_effect = ConnectionError("API nepasiekiamas")

    job = {"title": "X", "company": "Y", "snippet": "..."}
    result, _ = ranker.score_job(job, candidate_profile="test profile")

    jsonschema.validate(instance=result, schema=ranker.RANK_RESULT_SCHEMA)


# --- Konsoliduotas "evidence kontrakto" testas (3 sąlygos viename teste) ---

@patch("ranker.client")
def test_evidence_contract_full_specification(mock_client):
    """
    KONSOLIDUOTAS testas trims evidence kontrakto sąlygoms:
    1. Modelio atsakymas TURI evidence lauką
    2. Evidence PATIKRINAMAS, ar randamas job_text (skelbimo tekste)
    3. Jei NErandamas - balas sumažinamas (downgrade), rezultatas NEATMETAMAS
       visiškai (nes tai galėtų būti tiesiog formato/interpretacijos
       nesutapimas, ne būtinai visiška nesąmonė) - bet jis nebegali klaidinti
       aukštu balu.

    Du atskiri pod-testai tame pačiame teste: (a) grounded atvejis palieka
    balą, (b) ungrounded atvejis jį sumažina.
    """
    job_text_snippet = "Reikalaujama 5 metų Python programavimo patirties."
    job = {"title": "Developer", "company": "TestCo", "snippet": job_text_snippet}

    # (a) Evidence YRA ir RANDAMAS job_text - balas išlieka
    mock_client.messages.create.return_value = _mock_text_response(
        '{"score": 8, "reason": "Atitinka.", '
        '"evidence": "5 metų Python programavimo patirties"}'
    )
    result_grounded, _ = ranker.score_job(job, candidate_profile="test")
    assert "evidence" in result_grounded  # (1) laukas yra
    assert result_grounded["grounded"] is True  # (2) rastas job_text
    assert result_grounded["score"] == 8  # NEsumažintas, nes pagrįstas

    # (b) Evidence YRA, bet NErandamas job_text (fabrikuotas) - balas sumažinamas
    mock_client.messages.create.return_value = _mock_text_response(
        '{"score": 8, "reason": "Atitinka.", '
        '"evidence": "10 metų kvantinės kriptografijos patirties"}'
    )
    result_ungrounded, _ = ranker.score_job(job, candidate_profile="test")
    assert "evidence" in result_ungrounded  # (1) laukas yra
    assert result_ungrounded["grounded"] is False  # (2) NErastas job_text
    assert result_ungrounded["score"] <= ranker.DOWNGRADE_SCORE_CAP  # (3) sumažintas
    assert result_ungrounded["score"] < result_grounded["score"]  # akivaizdus skirtumas
