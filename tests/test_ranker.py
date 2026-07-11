"""
Testai ranker.py (tool-calling agent loop) logikai. Anthropic API kvietimai
mockinami - testai NEATLIEKA realių API kvietimų ir neveikia be tinklo/rakto.
"""

from unittest.mock import MagicMock, patch

import ranker


def _mock_text_response(text: str, stop_reason: str = "end_turn"):
    """Sukuria mock atsakymą su galutiniu tekstu (be tool use)."""
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = text
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.stop_reason = stop_reason
    return mock_response


def _mock_tool_use_response(tool_name: str, tool_input: dict, tool_use_id: str = "tool_1"):
    """Sukuria mock atsakymą, kuriame Claude prašo iškviesti įrankį."""
    mock_block = MagicMock()
    mock_block.type = "tool_use"
    mock_block.id = tool_use_id
    mock_block.name = tool_name
    mock_block.input = tool_input
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.stop_reason = "tool_use"
    return mock_response


# Atgalinio suderinamumo pravardė - kai kurie senesni testai naudoja šį vardą
_mock_response = _mock_text_response


@patch("ranker.client")
def test_score_job_parses_valid_json(mock_client):
    mock_client.messages.create.return_value = _mock_text_response(
        '{"score": 8, "reason": "Gerai atitinka patirtį.", "evidence": "5+ metų projektų valdymo patirties"}'
    )

    job = {"title": "IT Project Manager", "company": "Test",
           "snippet": "Reikalaujama 5+ metų projektų valdymo patirties."}
    result, stats = ranker.score_job(job, candidate_profile="test profile")

    assert result["score"] == 8
    assert "atitinka" in result["reason"]
    assert stats["api_calls_made"] == 1
    assert stats["tool_calls_made"] == 0


@patch("ranker.client")
def test_score_job_strips_markdown_json_fences(mock_client):
    mock_client.messages.create.return_value = _mock_text_response(
        '```json\n{"score": 5, "reason": "Vidutinis atitikimas.", "evidence": "Reikalinga Java patirtis"}\n```'
    )

    job = {"title": "Sales Manager", "company": "Test",
           "snippet": "Reikalinga Java patirtis."}
    result, _ = ranker.score_job(job, candidate_profile="test profile")

    assert result["score"] == 5


@patch("ranker.client")
def test_score_job_handles_malformed_json_gracefully(mock_client):
    """
    Nevalidus JSON dabar bando dar kartą (žr. GENERAL retry logiką) iki
    max_iterations kartų - jei modelis NUOSEKLIAI grąžina nevalidų tekstą
    (kaip šiame teste, kur mock visada grąžina tą patį), galiausiai vis
    tiek grąžinamas saugus error rezultatas, tik po visų bandymų, ne po pirmo.
    """
    mock_client.messages.create.return_value = _mock_text_response("nebe JSON tekstas be jokios prasmes")

    job = {"title": "X", "company": "Y", "snippet": "..."}
    result, stats = ranker.score_job(job, candidate_profile="test profile")

    # Klaidos atveju turi grąžinti saugų default'ą, o ne mesti išimtį
    assert result["score"] == 0
    assert "reason" in result
    assert stats["api_calls_made"] == ranker.MAX_AGENT_ITERATIONS  # visos iteracijos išnaudotos bandant


@patch("ranker.client")
def test_score_job_handles_api_exception(mock_client):
    mock_client.messages.create.side_effect = ConnectionError("API nepasiekiamas")

    job = {"title": "X", "company": "Y", "snippet": "..."}
    result, stats = ranker.score_job(job, candidate_profile="test profile")

    assert result["score"] == 0
    assert stats["api_calls_made"] == 1  # bandymas skaičiuojamas, net jei nepavyko


# --- Tool use / agent loop testai ------------------------------------------

@patch("scraper.fetch_page_text")
@patch("ranker.client")
def test_score_job_calls_tool_when_model_requests_it(mock_client, mock_fetch):
    """
    Simuliuoja: Claude pirmame žingsnyje prašo get_full_job_description,
    gauna rezultatą, antrame žingsnyje grąžina galutinį JSON.
    """
    mock_fetch.return_value = "Pilnas skelbimo tekstas. Reikalaujama Agile ir SQL patirtis su visais reikalavimais."
    mock_client.messages.create.side_effect = [
        _mock_tool_use_response("get_full_job_description", {"url": "https://example.test/job/1"}),
        _mock_text_response('{"score": 9, "reason": "Po pilno teksto perskaitymo - puikiai tinka.", "evidence": "Reikalaujama Agile ir SQL patirtis"}'),
    ]

    job = {
        "title": "IT Project Manager",
        "company": "Test",
        "url": "https://example.test/job/1",
        "snippet": "Trumpas, neaiškus anonsas.",
    }
    result, stats = ranker.score_job(job, candidate_profile="test profile")

    assert result["score"] == 9
    assert stats["api_calls_made"] == 2  # 2 kreipimaisi į Claude
    assert stats["tool_calls_made"] == 1  # 1 realus tool use
    mock_fetch.assert_called_once_with("https://example.test/job/1")


@patch("ranker.client")
def test_score_job_does_not_call_tool_when_snippet_sufficient(mock_client):
    """Jei modelis iškart atsako be tool use, tool_calls_made turi likti 0."""
    mock_client.messages.create.return_value = _mock_text_response(
        '{"score": 7, "reason": "Anonso pakako vertinimui.", "evidence": "Reikalinga projektų valdymo patirtis"}'
    )

    job = {"title": "X", "company": "Y", "snippet": "Reikalinga projektų valdymo patirtis."}
    result, stats = ranker.score_job(job, candidate_profile="test profile")

    assert result["score"] == 7
    assert stats["tool_calls_made"] == 0
    assert stats["api_calls_made"] == 1


@patch("scraper.fetch_page_text")
@patch("ranker.client")
def test_score_job_handles_tool_execution_failure_gracefully(mock_client, mock_fetch):
    """
    Jei get_full_job_description meta išimtį (svetainė neatsidaro ir pan.),
    tool_result turi būti pažymėtas is_error=True, o agent loop turi TĘSTIS
    (ne lūžti), leidžiant modeliui atsakyti su tuo, ką jau turi.
    """
    mock_fetch.side_effect = TimeoutError("puslapis neatsidarė")
    mock_client.messages.create.side_effect = [
        _mock_tool_use_response("get_full_job_description", {"url": "https://example.test/job/1"}),
        _mock_text_response('{"score": 4, "reason": "Įvertinta tik pagal trumpą anonsą, nes pilnas tekstas nepasiekiamas.", "evidence": "Reikalinga bazinė IT patirtis"}'),
    ]

    job = {
        "title": "X", "company": "Y",
        "url": "https://example.test/job/1", "snippet": "Reikalinga bazinė IT patirtis.",
    }
    result, stats = ranker.score_job(job, candidate_profile="test profile")

    assert result["score"] == 4
    assert stats["tool_calls_made"] == 1

    # Patikriname, kad tool_result žingsnis realiai turėjo is_error=True
    second_call_messages = mock_client.messages.create.call_args_list[1].kwargs["messages"]
    tool_result_message = second_call_messages[-1]
    assert tool_result_message["content"][0]["is_error"] is True


@patch("ranker.client")
def test_score_job_agent_loop_exceeds_max_iterations(mock_client):
    """
    Jei modelis vis kviečia įrankį ir niekada nepasiekia end_turn, agent loop
    turi sustoti po max_iterations ir grąžinti saugų default'ą, o ne kabinti
    procesą amžinai.
    """
    with patch("scraper.fetch_page_text", return_value="tekstas"):
        mock_client.messages.create.return_value = _mock_tool_use_response(
            "get_full_job_description", {"url": "https://example.test/job/1"}
        )

        job = {"title": "X", "company": "Y", "url": "https://example.test/job/1", "snippet": "..."}
        result, stats = ranker.score_job(job, candidate_profile="test", max_iterations=3)

    assert result["score"] == 0
    assert "iteracijų limitas" in result["reason"]
    assert stats["api_calls_made"] == 3
    assert stats["tool_calls_made"] == 3


def test_execute_tool_unknown_tool_returns_error():
    text, is_error = ranker._execute_tool("nezinomas_irankis", {}, "https://x.test/expected")
    assert is_error is True
    assert "Nežinomas įrankis" in text


@patch("scraper.fetch_page_text")
def test_execute_tool_get_full_job_description_success(mock_fetch):
    mock_fetch.return_value = "Pilnas tekstas"
    text, is_error = ranker._execute_tool("get_full_job_description", {}, "https://x.test/expected")
    assert is_error is False
    assert text == "Pilnas tekstas"


@patch("scraper.fetch_page_text")
def test_execute_tool_get_full_job_description_handles_exception(mock_fetch):
    mock_fetch.side_effect = RuntimeError("tinklo klaida")
    text, is_error = ranker._execute_tool("get_full_job_description", {}, "https://x.test/expected")
    assert is_error is True
    assert "tinklo klaida" in text


# --- SSRF apsaugos testai ----------------------------------------------------

@patch("scraper.fetch_page_text")
def test_execute_tool_uses_expected_url_not_model_provided_url(mock_fetch):
    """
    KRITINIS SAUGUMO testas: net jei tool_input (modelio pateikti parametrai)
    turėtų "url" raktą su VISAI KITU (potencialiai pavojingu) adresu,
    _execute_tool TURI naudoti TIK expected_job_url, niekada tool_input.
    """
    mock_fetch.return_value = "turinys"

    malicious_input = {"url": "http://169.254.169.254/latest/meta-data/"}
    ranker._execute_tool("get_full_job_description", malicious_input, "https://real-job-site.test/job/1")

    # fetch_page_text turėjo būti iškviestas su TIKRUOJU (expected) URL,
    # NE su tuo, kurį "pasiūlė" tool_input
    mock_fetch.assert_called_once_with("https://real-job-site.test/job/1")


@patch("scraper.fetch_page_text")
def test_execute_tool_ignores_arbitrary_tool_input_completely(mock_fetch):
    """Net visiškai tuščias arba nesusijęs tool_input neturi įtakos - naudojamas TIK expected_job_url."""
    mock_fetch.return_value = "turinys"

    ranker._execute_tool("get_full_job_description", {"random_key": "random_value"}, "https://real.test/job/2")

    mock_fetch.assert_called_once_with("https://real.test/job/2")


def test_tools_schema_has_no_url_parameter():
    """
    Formalus kontrakto testas: TOOLS schema NETURI turėti "url" (ar bet kokio
    kito) parametro get_full_job_description įrankiui - modelis fiziškai
    negali pateikti URL, nes schema to neleidžia.
    """
    tool = next(t for t in ranker.TOOLS if t["name"] == "get_full_job_description")
    assert tool["input_schema"]["properties"] == {}
    assert tool["input_schema"].get("additionalProperties") is False


@patch("ranker.client")
def test_score_job_calls_tool_with_job_own_url_regardless_of_model_suggestion(mock_client):
    """
    End-to-end SSRF testas per score_job(): net jei modelis (per klaidą ar
    prompt injection) grąžintų tool_use su "url" argumentu, realiai
    iškviečiamas URL turi būti PATIES skelbimo url, ne modelio pasiūlytas.
    """
    with patch("scraper.fetch_page_text") as mock_fetch:
        mock_fetch.return_value = "Pilnas tekstas su Agile ir SQL patirtimi"
        mock_client.messages.create.side_effect = [
            _mock_tool_use_response(
                "get_full_job_description",
                {"url": "http://internal-secret-service.local/admin"},  # modelio "pasiūlytas" URL
            ),
            _mock_text_response(
                '{"score": 8, "reason": "Tinka.", "evidence": "Agile ir SQL patirtimi"}'
            ),
        ]

        job = {
            "title": "PM", "company": "Test",
            "url": "https://real-job-site.test/job/legit-123",  # TIKRASIS skelbimo URL
            "snippet": "Trumpas anonsas.",
        }
        ranker.score_job(job, candidate_profile="test")

        mock_fetch.assert_called_once_with("https://real-job-site.test/job/legit-123")


# --- rank_jobs agregavimo testai --------------------------------------------

@patch("ranker.score_job")
def test_rank_jobs_filters_by_min_score(mock_score_job):
    mock_score_job.side_effect = [
        ({"score": 9, "reason": "Puikiai tinka"}, {"api_calls_made": 1, "tool_calls_made": 0}),
        ({"score": 3, "reason": "Netinka"}, {"api_calls_made": 1, "tool_calls_made": 0}),
        ({"score": 7, "reason": "Tinka"}, {"api_calls_made": 2, "tool_calls_made": 1}),
    ]
    jobs = [
        {"title": "A", "url": "https://x/1"},
        {"title": "B", "url": "https://x/2"},
        {"title": "C", "url": "https://x/3"},
    ]

    matched, stats = ranker.rank_jobs(jobs, candidate_profile="test", min_score=7)

    assert len(matched) == 2
    assert [j["title"] for j in matched] == ["A", "C"]  # surikiuota mažėjančiai pagal balą
    assert stats["api_calls_made"] == 4  # 1 + 1 + 2
    assert stats["tool_calls_made"] == 1
    assert stats["api_call_errors"] == 0


@patch("ranker.score_job")
def test_rank_jobs_empty_input_returns_empty(mock_score_job):
    matched, stats = ranker.rank_jobs([], candidate_profile="test", min_score=7)
    assert matched == []
    assert stats == {"api_calls_made": 0, "api_call_errors": 0, "tool_calls_made": 0, "ungrounded_count": 0}
    mock_score_job.assert_not_called()


@patch("ranker.score_job")
def test_rank_jobs_counts_api_errors_in_stats(mock_score_job):
    """Patikrina, kad rank_jobs stats atskiria sėkmingus vertinimus nuo klaidų."""
    mock_score_job.side_effect = [
        ({"score": 8, "reason": "Gerai tinka"}, {"api_calls_made": 1, "tool_calls_made": 0}),
        ({"score": 0, "reason": "Vertinimo klaida: Connection error."}, {"api_calls_made": 1, "tool_calls_made": 0}),
    ]
    jobs = [
        {"title": "A", "url": "https://x/1"},
        {"title": "B", "url": "https://x/2"},
    ]

    matched, stats = ranker.rank_jobs(jobs, candidate_profile="test", min_score=7)

    assert stats["api_calls_made"] == 2
    assert stats["api_call_errors"] == 1


# --- Retry / preflight testai (nepasikeitė nuo ankstesnės versijos) --------

@patch("tenacity.nap.time.sleep", return_value=None)
@patch("ranker.client")
def test_call_claude_retries_on_retryable_error_then_succeeds(mock_client, mock_sleep):
    """Simuliuoja: pirmi 2 bandymai meta RetryableError, trečias pavyksta."""
    import anthropic
    import httpx

    fake_request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    mock_client.messages.create.side_effect = [
        anthropic.APIConnectionError(request=fake_request),
        anthropic.APIConnectionError(request=fake_request),
        _mock_text_response('{"score": 6, "reason": "Po retry pavyko.", "evidence": "Bendra IT patirtis"}'),
    ]

    job = {"title": "X", "company": "Y", "snippet": "Bendra IT patirtis reikalinga."}
    result, stats = ranker.score_job(job, candidate_profile="test")

    assert result["score"] == 6
    assert mock_client.messages.create.call_count == 3
    assert stats["api_calls_made"] == 1  # tai VIENAS "loginis" score_job kreipimasis (su retry viduje)


@patch("tenacity.nap.time.sleep", return_value=None)
@patch("ranker.client")
def test_call_claude_gives_up_after_max_attempts(mock_client, mock_sleep):
    """Jei visi 3 bandymai nepavyksta, score_job grąžina saugų default'ą (score=0), ne išimtį."""
    import anthropic
    import httpx

    fake_request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    mock_client.messages.create.side_effect = anthropic.APIConnectionError(request=fake_request)

    job = {"title": "X", "company": "Y", "snippet": "..."}
    result, stats = ranker.score_job(job, candidate_profile="test")

    assert result["score"] == 0
    assert mock_client.messages.create.call_count == 3  # stop_after_attempt(3)


@patch("ranker.client")
def test_non_retryable_error_does_not_retry(mock_client):
    """AuthenticationError (bloga API rakto reikšmė) neturėtų būti kartojama - nepavyks ir kitą kartą."""
    import anthropic
    import httpx

    fake_response = httpx.Response(
        status_code=401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    mock_client.messages.create.side_effect = anthropic.AuthenticationError(
        message="invalid key", response=fake_response, body=None
    )

    job = {"title": "X", "company": "Y", "snippet": "..."}
    result, stats = ranker.score_job(job, candidate_profile="test")

    assert result["score"] == 0
    assert mock_client.messages.create.call_count == 1  # be retry


@patch("ranker.client")
def test_preflight_check_success(mock_client):
    mock_client.messages.create.return_value = _mock_text_response("pong")

    ok, err = ranker.preflight_check()

    assert ok is True
    assert err is None
    mock_client.messages.create.assert_called_once()
    # Preflight turi būti pigus - max_tokens=1
    _, kwargs = mock_client.messages.create.call_args
    assert kwargs["max_tokens"] == 1


@patch("ranker.client")
def test_preflight_check_failure_returns_error_message(mock_client):
    import anthropic
    import httpx

    fake_response = httpx.Response(
        status_code=401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    mock_client.messages.create.side_effect = anthropic.AuthenticationError(
        message="invalid x-api-key", response=fake_response, body=None
    )

    ok, err = ranker.preflight_check()

    assert ok is False
    assert err is not None
    assert "invalid x-api-key" in err


# --- Grounding (evidence field) testai --------------------------------------

@patch("ranker.client")
def test_score_job_captures_evidence_field(mock_client):
    mock_client.messages.create.return_value = _mock_text_response(
        '{"score": 8, "reason": "Gerai atitinka.", "evidence": "Reikalaujama 5+ metų patirties projektų valdyme"}'
    )

    job = {"title": "PM", "company": "Test", "snippet": "..."}
    result, _ = ranker.score_job(job, candidate_profile="test profile")

    assert result["evidence"] == "Reikalaujama 5+ metų patirties projektų valdyme"


@patch("ranker.client")
def test_score_job_missing_evidence_key_entirely_is_schema_error(mock_client):
    """
    Jei modelis apskritai NEGRĄŽINA 'evidence' rakto (ne tik tuščio), tai yra
    JSON SCHEMA VALIDACIJOS klaida (žr. REQUIRED_FIELDS) - balas=0, nes
    atsakymas apskritai neatitinka sutarto struktūrinio kontrakto.
    """
    mock_client.messages.create.return_value = _mock_text_response(
        '{"score": 8, "reason": "Gerai atitinka."}'  # be evidence rakto apskritai
    )

    job = {"title": "PM", "company": "Test", "snippet": "..."}
    result, _ = ranker.score_job(job, candidate_profile="test profile")

    assert result["score"] == 0
    assert "schemos" in result["reason"] or "evidence" in result["reason"]


@patch("ranker.client")
def test_score_job_present_but_empty_evidence_is_downgraded_not_zeroed(mock_client):
    """
    Jei 'evidence' raktas PRESENT, bet jo reikšmė tuščia eilutė (modelis
    sąmoningai neturėjo ką pacituoti) - tai NĖRA schema klaida (raktas yra),
    bet YRA grounding nesėkmė - balas nužeminamas iki DOWNGRADE_SCORE_CAP,
    ne nunulinamas iki 0 (tai būtų per griežta - modelis sąžiningai
    pripažino, kad neturi ką pacituoti).
    """
    mock_client.messages.create.return_value = _mock_text_response(
        '{"score": 8, "reason": "Gerai atitinka.", "evidence": ""}'
    )

    job = {"title": "PM", "company": "Test", "snippet": "..."}
    result, _ = ranker.score_job(job, candidate_profile="test profile")

    assert result["score"] == ranker.DOWNGRADE_SCORE_CAP
    assert result["grounded"] is False
    assert "nužemintas" in result["evidence"] or "logus" in result["evidence"]


@patch("ranker.logger")
@patch("ranker.client")
def test_score_job_logs_warning_when_evidence_ungrounded(mock_client, mock_logger):
    mock_client.messages.create.return_value = _mock_text_response(
        '{"score": 8, "reason": "Gerai atitinka.", "evidence": ""}'
    )

    job = {"title": "PM", "company": "Test", "snippet": "..."}
    ranker.score_job(job, candidate_profile="test profile")

    mock_logger.warning.assert_called_once()
    warning_message = mock_logger.warning.call_args[0][0]
    assert "evidence" in warning_message.lower() or "nužeminamas" in warning_message.lower()


@patch("ranker.client")
def test_score_job_empty_string_evidence_treated_as_missing(mock_client):
    """Tuščia evidence eilutė (ne visai nebuvimas, o tuščias string) irgi turi būti pažymėta."""
    mock_client.messages.create.return_value = _mock_text_response(
        '{"score": 6, "reason": "Vidutiniškai tinka.", "evidence": ""}'
    )

    job = {"title": "PM", "company": "Test", "snippet": "..."}
    result, _ = ranker.score_job(job, candidate_profile="test profile")

    assert result["evidence"] != ""  # pakeista placeholder'iu


@patch("ranker.score_job")
def test_rank_jobs_passes_through_evidence_to_job_dict(mock_score_job):
    mock_score_job.return_value = (
        {"score": 8, "reason": "Tinka", "evidence": "Reikalaujama Python patirtis"},
        {"api_calls_made": 1, "tool_calls_made": 0},
    )
    jobs = [{"title": "A", "url": "https://x/1"}]

    matched, _ = ranker.rank_jobs(jobs, candidate_profile="test", min_score=7)

    assert matched[0]["match_evidence"] == "Reikalaujama Python patirtis"


# --- Determinizmas (temperature=0) testai -----------------------------------

@patch("ranker.client")
def test_call_claude_uses_temperature_zero(mock_client):
    """
    Vertinimas yra sprendimo priėmimo, ne kūrybinio teksto generavimo užduotis -
    temperature=0 sumažina atsitiktinį balo svyravimą pakartotinai vertinant
    tą patį skelbimą.
    """
    mock_client.messages.create.return_value = _mock_text_response(
        '{"score": 7, "reason": "...", "evidence": "..."}'
    )

    job = {"title": "X", "company": "Y", "snippet": "..."}
    ranker.score_job(job, candidate_profile="test")

    _, kwargs = mock_client.messages.create.call_args
    assert kwargs["temperature"] == 0


@patch("ranker.client")
def test_call_claude_uses_sufficient_max_tokens_to_avoid_json_truncation(mock_client):
    """
    REGRESIJOS testas realiam radiniui: gamyboje pastebėta JSON parse klaidų
    ("Expecting value", "Expecting ',' delimiter") - klasikiniai nutrūkusio
    (truncated) JSON požymiai, kai max_tokens per mažas pilnam structured
    output (score+reason+evidence+matched/missing_requirements). Ši riba
    NETURI sumažėti žemiau 1024 be sąmoningo sprendimo ir pakartotinio
    realaus patikrinimo.
    """
    mock_client.messages.create.return_value = _mock_text_response(
        '{"score": 7, "reason": "...", "evidence": "..."}'
    )

    job = {"title": "X", "company": "Y", "snippet": "..."}
    ranker.score_job(job, candidate_profile="test")

    _, kwargs = mock_client.messages.create.call_args
    assert kwargs["max_tokens"] >= 1024


@patch("ranker.client")
def test_score_job_downgrades_high_score_with_fabricated_evidence(mock_client):
    """
    TIKSLIAI vartotojo klausimo scenarijus: modelis grąžina AUKŠTĄ balą su
    "evidence", kurios REALIAI SKELBIME NĖRA (fabrikuota/sugalvota citata).
    Programinė grounding patikra tai turi aptikti ir balą priverstinai
    nužeminti - "Puikiai tinka" be realaus pagrindimo NEGALI likti 9/10.
    """
    mock_client.messages.create.return_value = _mock_text_response(
        '{"score": 9, "reason": "Puikiai tinka!", '
        '"evidence": "Reikalaujama 15 metų branduolinės inžinerijos patirties"}'
    )

    # Realiame skelbime apie tai NIEKUR neužsimenama - "evidence" yra fabrikuota
    job = {
        "title": "Pardavimų vadybininkas",
        "company": "Prekybos Grupė",
        "snippet": "Ieškome aktyvaus pardavimų vadybininko darbui su B2B klientais.",
    }
    result, _ = ranker.score_job(job, candidate_profile="test profile")

    assert result["grounded"] is False
    assert result["score"] <= ranker.DOWNGRADE_SCORE_CAP
    assert result["score"] < 9  # NEGALI likti originalus aukštas balas
    # "reason" laukas gali likti (audito tikslais), bet balas jau nebekelia klaidingo įspūdžio


@patch("ranker.client")
def test_score_job_recovers_from_garbage_non_empty_text(mock_client):
    """
    KRITINIS testas TIKSLIAI gamybos radiniui (2026-07): json.loads() meta
    LYGIAI TĄ PAČIĄ "Expecting value: line 1 column 1" klaidą tiek dėl
    TUŠČIO teksto, tiek dėl BET KOKIO NETUŠČIO, bet iškart nevalidaus teksto
    (pvz., vieno nutrūkusio simbolio "x"). Ankstesnis pataisymas tikrino tik
    tuštumą (`if not text`) ir šio atvejo NEPAGAUDAVO - dabar bendra
    retry-on-any-parse-failure logika turi tai pagauti taip pat.
    """
    mock_client.messages.create.side_effect = [
        _mock_text_response("x"),  # netuščias, bet visiškai nevalidus JSON
        _mock_text_response('{"score": 6, "reason": "Tinka.", "evidence": "SQL patirtis"}'),
    ]

    job = {"title": "IT PM", "company": "Test", "snippet": "SQL patirtis reikalinga."}
    result, stats = ranker.score_job(job, candidate_profile="test")

    assert result["score"] == 6  # antras bandymas pavyko
    assert stats["api_calls_made"] == 2


@patch("ranker.client")
def test_preflight_check_does_not_require_temperature(mock_client):
    """Preflight yra tik pasiekiamumo patikra ('ping') - temperature čia nesvarbu, netikriname."""
    mock_client.messages.create.return_value = _mock_text_response("pong")
    ok, err = ranker.preflight_check()
    assert ok is True


# --- Tuščio atsakymo atkūrimo testai (realus gamybos radinys, 2026-07) -----

def _mock_empty_response(stop_reason: str = "end_turn"):
    """Simuliuoja realų gamyboje pastebėtą atvejį: atsakymas be jokio teksto bloko."""
    mock_response = MagicMock()
    mock_response.content = []  # jokių blokų - nei text, nei tool_use
    mock_response.stop_reason = stop_reason
    return mock_response


@patch("ranker.client")
def test_score_job_recovers_from_empty_response_by_retrying(mock_client):
    """
    KRITINIS testas realiam gamybos radiniui: jei Claude grąžina tuščią
    atsakymą (be teksto), score_job TURI paprašyti dar kartą (naudodamas
    likusią iteracijų kvotą), o ne iškart pasiduoti su klaida.
    """
    mock_client.messages.create.side_effect = [
        _mock_empty_response(),
        _mock_text_response('{"score": 7, "reason": "Tinka.", "evidence": "Reikalinga IT patirtis"}'),
    ]

    job = {"title": "IT PM", "company": "Test", "snippet": "Reikalinga IT patirtis."}
    result, stats = ranker.score_job(job, candidate_profile="test")

    assert result["score"] == 7  # antras bandymas pavyko
    assert stats["api_calls_made"] == 2  # abu kvietimai įskaičiuoti


@patch("ranker.client")
def test_score_job_fails_gracefully_if_empty_response_persists(mock_client):
    """
    Jei tuščias atsakymas kartojasi VISAS iteracijas (max_iterations), score_job
    turi grąžinti saugų error rezultatą (score=0), o ne kabinti procesą ar
    mesti nesugautą išimtį.
    """
    mock_client.messages.create.return_value = _mock_empty_response()

    job = {"title": "IT PM", "company": "Test", "snippet": "..."}
    result, stats = ranker.score_job(job, candidate_profile="test", max_iterations=3)

    assert result["score"] == 0
    assert result["reason"].startswith("Vertinimo klaida:")
    assert stats["api_calls_made"] == 3  # visos 3 iteracijos išnaudotos


@patch("ranker.client")
def test_score_job_logs_stop_reason_when_response_empty(mock_client):
    """Diagnostikai svarbu matyti stop_reason, kai atsakymas tuščias - padeda atskirti priežastis ateityje."""
    with patch("ranker.logger") as mock_logger:
        mock_client.messages.create.side_effect = [
            _mock_empty_response(stop_reason="max_tokens"),
            _mock_text_response('{"score": 5, "reason": "...", "evidence": "..."}'),
        ]

        job = {"title": "X", "company": "Y", "snippet": "..."}
        ranker.score_job(job, candidate_profile="test")

        warning_call = mock_logger.warning.call_args
        assert warning_call.kwargs["extra"]["stop_reason"] == "max_tokens"
