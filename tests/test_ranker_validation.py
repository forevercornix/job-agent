"""Pure RankResponse, grounding and requirement-list validation tests."""

import pytest
from pydantic import ValidationError

import ranker

# --- ThinHarness structured output model ------------------------------------

@pytest.mark.parametrize("field", ["score", "reason", "evidence"])
def test_rank_response_rejects_missing_required_field(field):
    payload = {"score": 8, "reason": "Gerai tinka", "evidence": "citata"}
    payload.pop(field)

    with pytest.raises(ValidationError) as error:
        ranker.RankResponse.model_validate(payload)

    assert field in str(error.value)


def test_rank_response_rejects_blank_reason():
    with pytest.raises(ValidationError, match="reason must not be blank"):
        ranker.RankResponse(score=8, reason="   ", evidence="citata")


def test_rank_response_rejects_non_string_evidence():
    with pytest.raises(ValidationError) as error:
        ranker.RankResponse(score=8, reason="Gerai tinka", evidence=12345)

    assert "evidence" in str(error.value)


def test_rank_response_rejects_non_numeric_score():
    with pytest.raises(ValidationError) as error:
        ranker.RankResponse(score="labai geras", reason="Gerai tinka", evidence="citata")

    assert "score" in str(error.value)


def test_rank_response_accepts_empty_evidence_and_defaults_optional_lists():
    response = ranker.RankResponse(score=5, reason="Tinka", evidence="")

    assert response.evidence == ""
    assert response.matched_requirements == []
    assert response.missing_requirements == []


def test_rank_response_keeps_requirement_inputs_permissive_for_legacy_coercion():
    response = ranker.RankResponse(
        score="8",
        reason="Tinka",
        evidence="citata",
        matched_requirements=["SQL", 5],
        missing_requirements="ne sąrašas",
        extra_field="ignoruojamas",
    )

    assert response.score == 8
    assert response.matched_requirements == ["SQL", 5]
    assert response.missing_requirements == "ne sąrašas"


# --- Evidence grounding (substring/fuzzy) testai ----------------------------

def test_is_evidence_grounded_exact_substring_match():
    source = "Ieškome IT projektų vadovo su Agile patirtimi ir SQL žiniomis."
    assert ranker._is_evidence_grounded("Agile patirtimi ir SQL žiniomis", source) is True


def test_is_evidence_grounded_case_insensitive():
    source = "Reikalaujama AGILE PATIRTIS ir SQL."
    assert ranker._is_evidence_grounded("agile patirtis", source) is True


def test_is_evidence_grounded_fuzzy_match_slight_rewording():
    """Modelis šiek tiek perfrazavo (linksnis/žodžių tvarka), bet tai akivaizdžiai tas pats fragmentas."""
    source = "Reikalaujama 5 metų patirties projektų valdyme ir Agile metodikose."
    # Beveik identiška, tik nedidelis skirtumas ("patirties" vs "patirtis")
    assert ranker._is_evidence_grounded("5 metų patirtis projektų valdyme", source) is True


def test_is_evidence_grounded_returns_false_for_fabricated_text():
    """
    KRITINIS testas: jei evidence yra tekstas, kurio VISIŠKAI NĖRA skelbime
    (modelis "sugalvojo" citatą), grounding patikra TURI grąžinti False.
    """
    source = "Ieškome pardavimų vadybininko su B2B patirtimi mažmeninėje prekyboje."
    fabricated_evidence = "Reikalaujama 10 metų branduolinės fizikos patirties"
    assert ranker._is_evidence_grounded(fabricated_evidence, source) is False


def test_is_evidence_grounded_returns_false_for_empty_evidence():
    assert ranker._is_evidence_grounded("", "Bet koks tekstas čia.") is False


def test_is_evidence_grounded_returns_false_for_empty_source():
    assert ranker._is_evidence_grounded("citata", "") is False


def test_is_evidence_grounded_returns_false_for_unrelated_short_source():
    assert ranker._is_evidence_grounded("ilga citata apie kažką", "trumpas") is False


def test_is_evidence_grounded_respects_custom_threshold():
    source = "Reikalaujama Python programavimo patirties."
    similar_but_not_quite = "Reikalaujama Java programavimo patirties."
    # Su labai aukštu threshold (0.99) beveik joks fuzzy match nepraeis
    assert ranker._is_evidence_grounded(similar_but_not_quite, source, fuzzy_threshold=0.99) is False
    # Su žemesniu threshold (0.7) šis panašus (bet ne identiškas) fragmentas gali praeiti
    assert ranker._is_evidence_grounded(similar_but_not_quite, source, fuzzy_threshold=0.5) is True


# --- matched_requirements / missing_requirements coercion testai -----------

def test_coerce_string_list_accepts_valid_list():
    result = ranker._coerce_string_list(["SQL", "Agile", "Scrum"])
    assert result == ["SQL", "Agile", "Scrum"]


def test_coerce_string_list_returns_empty_for_non_list_input():
    assert ranker._coerce_string_list("ne sąrašas") == []
    assert ranker._coerce_string_list(None) == []
    assert ranker._coerce_string_list(42) == []


def test_coerce_string_list_filters_empty_and_invalid_items():
    result = ranker._coerce_string_list(["SQL", "", "   ", None, {"nested": "dict"}, "Agile"])
    assert result == ["SQL", "Agile"]


def test_coerce_string_list_respects_max_items_limit():
    long_list = [f"item{i}" for i in range(20)]
    result = ranker._coerce_string_list(long_list, max_items=5)
    assert len(result) == 5


def test_coerce_string_list_converts_numbers_to_strings():
    result = ranker._coerce_string_list([5, 3.14, "text"])
    assert result == ["5", "3.14", "text"]
