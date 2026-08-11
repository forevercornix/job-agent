"""ThinHarness 0.6.0 provider retry integration tests through score_job()."""

import asyncio
import json
from unittest.mock import patch

import httpx
import pytest
from thinharness import AnthropicMessagesModel, AnthropicProvider

import ranker


def _job(**overrides):
    job = {
        "title": "IT Project Manager",
        "company": "TestCo",
        "url": "https://jobs.test/1",
        "source": "test",
        "snippet": "Reikalaujama SQL patirtis.",
    }
    job.update(overrides)
    return job


def _response(content, *, stop_reason="end_turn"):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-contract-test",
        "content": content,
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def _final_response(*, score=8, evidence="SQL patirtis"):
    output = json.dumps(
        {"score": score, "reason": "Tinka.", "evidence": evidence},
        ensure_ascii=False,
    )
    return _response([{"type": "text", "text": output}])


def _tool_response():
    return _response(
        [
            {
                "type": "tool_use",
                "id": "tool-1",
                "name": "get_full_job_description",
                "input": {},
            }
        ],
        stop_reason="tool_use",
    )


def _real_anthropic_model(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AnthropicProvider(
        api_key="test-key",
        base_url="https://provider.test",
        http_client=client,
        request_retries=ranker.REQUEST_RETRIES,
        request_retry_backoff=0,
    )
    model = AnthropicMessagesModel(
        "claude-contract-test",
        provider=provider,
        max_tokens=1024,
    )
    return model, client


def _close(client):
    asyncio.run(client.aclose())


def test_transient_provider_failures_use_two_retries_inside_score_job():
    statuses = [429, 529]
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        if statuses:
            return httpx.Response(statuses.pop(0), text="transient", request=request)
        return httpx.Response(200, json=_final_response(score=6), request=request)

    model, client = _real_anthropic_model(respond)
    try:
        result, stats = ranker.score_job(_job(), "profilis", model=model)
    finally:
        _close(client)

    assert result["score"] == 6
    assert result["grounded"] is True
    assert len(requests) == 3
    assert requests[0] == requests[1] == requests[2]
    assert stats == {"api_calls_made": 1, "tool_calls_made": 0}


@patch("scraper.fetch_page_text", return_value="Pilnas tekstas su ERP patirtimi")
def test_retry_after_tool_call_keeps_session_and_does_not_fetch_again(mock_fetch):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(200, json=_tool_response(), request=request)
        if len(requests) == 2:
            return httpx.Response(529, text="overloaded", request=request)
        return httpx.Response(
            200,
            json=_final_response(score=7, evidence="ERP patirtimi"),
            request=request,
        )

    model, client = _real_anthropic_model(respond)
    try:
        result, stats = ranker.score_job(
            _job(snippet="Trumpas."),
            "profilis",
            model=model,
        )
    finally:
        _close(client)

    assert result["score"] == 7
    assert result["grounded"] is True
    assert len(requests) == 3
    assert requests[1] == requests[2]
    assert requests[1]["messages"][-1]["content"][0]["type"] == "tool_result"
    mock_fetch.assert_called_once_with("https://jobs.test/1")
    assert stats == {"api_calls_made": 2, "tool_calls_made": 1}


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_non_retryable_provider_failures_make_one_request(status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, text="invalid request", request=request)

    model, client = _real_anthropic_model(respond)
    try:
        result, stats = ranker.score_job(_job(), "profilis", model=model)
    finally:
        _close(client)

    assert result["score"] == 0
    assert f"provider error {status}" in result["reason"]
    assert len(requests) == 1
    assert stats == {"api_calls_made": 1, "tool_calls_made": 0}


def test_exhausted_provider_attempt_count_remains_approximate():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(529, text="overloaded", request=request)

    model, client = _real_anthropic_model(respond)
    try:
        result, stats = ranker.score_job(_job(), "profilis", model=model)
    finally:
        _close(client)

    assert result["score"] == 0
    assert len(requests) == 3
    assert stats == {"api_calls_made": 1, "tool_calls_made": 0}
