"""
Dedikuoti testai naujoms LLM reliability funkcijoms ranker.py:
- _validate_schema (JSON schema validacija)
- _is_evidence_grounded (evidence substring/fuzzy patikra)
- _coerce_string_list (matched_requirements/missing_requirements apdorojimas)

Šie testai atskirti nuo test_ranker.py, nes tikrina PAČIAS validacijos
funkcijas izoliuotai (be Claude API mock'inimo), kad būtų aišku, kas tiksliai
testuojama - schema kontraktas ir grounding logika, ne visas agent loop.
"""

import ranker

# --- JSON Schema validacijos testai -----------------------------------------

def test_validate_schema_accepts_complete_valid_response():
    result = {"score": 8, "reason": "Gerai tinka", "evidence": "citata"}
    is_valid, error = ranker._validate_schema(result)
    assert is_valid is True
    assert error is None


def test_validate_schema_rejects_missing_score():
    result = {"reason": "Gerai tinka", "evidence": "citata"}
    is_valid, error = ranker._validate_schema(result)
    assert is_valid is False
    assert "score" in error


def test_validate_schema_rejects_missing_reason():
    result = {"score": 8, "evidence": "citata"}
    is_valid, error = ranker._validate_schema(result)
    assert is_valid is False
    assert "reason" in error


def test_validate_schema_rejects_missing_evidence():
    result = {"score": 8, "reason": "Gerai tinka"}
    is_valid, error = ranker._validate_schema(result)
    assert is_valid is False
    assert "evidence" in error


def test_validate_schema_rejects_empty_reason():
    result = {"score": 8, "reason": "   ", "evidence": "citata"}
    is_valid, error = ranker._validate_schema(result)
    assert is_valid is False


def test_validate_schema_rejects_non_string_evidence():
    result = {"score": 8, "reason": "Gerai tinka", "evidence": 12345}
    is_valid, error = ranker._validate_schema(result)
    assert is_valid is False
    assert "evidence" in error


def test_validate_schema_rejects_non_numeric_score():
    result = {"score": "labai geras", "reason": "Gerai tinka", "evidence": "citata"}
    is_valid, error = ranker._validate_schema(result)
    assert is_valid is False
    assert "score" in error


def test_validate_schema_accepts_empty_evidence_string():
    """Tuščia evidence eilutė - VALIDI schemos prasme (raktas yra, tipas teisingas),
    net jei vėliau bus laikoma "negrounded" - tai skirtingi patikrinimo sluoksniai."""
    result = {"score": 5, "reason": "...", "evidence": ""}
    is_valid, error = ranker._validate_schema(result)
    assert is_valid is True


def test_validate_schema_accepts_extra_unexpected_fields():
    """Papildomi laukai (matched_requirements ir pan.) neturi sugriauti validacijos."""
    result = {"score": 8, "reason": "...", "evidence": "citata", "extra_field": "kažkas"}
    is_valid, error = ranker._validate_schema(result)
    assert is_valid is True


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
