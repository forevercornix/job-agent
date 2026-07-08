"""Testai format_email.py logikai."""

import json
import os
import tempfile
from unittest.mock import patch

import format_email

SAMPLE_JOBS = [
    {
        "title": "IT Projektų vadovas",
        "company": "UAB Test",
        "source": "ExampleJobBoard1",
        "url": "https://example.com/1",
        "match_score": 9,
        "match_reason": "Puikiai atitinka patirtį.",
    }
]


def _write_matched_jobs(tmp_path, jobs):
    path = os.path.join(tmp_path, "matched_jobs.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False)
    return path


def test_format_email_body_returns_none_when_file_missing():
    with patch.object(format_email.config, "OUTPUT_FILE", "/tmp/does_not_exist_xyz.json"):
        assert format_email.format_email_body() is None


def test_format_email_body_returns_none_when_no_matches():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = _write_matched_jobs(tmp_dir, [])
        with patch.object(format_email.config, "OUTPUT_FILE", path):
            assert format_email.format_email_body() is None


def test_format_email_body_includes_key_fields():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = _write_matched_jobs(tmp_dir, SAMPLE_JOBS)
        with patch.object(format_email.config, "OUTPUT_FILE", path):
            with patch.object(format_email.config, "MIN_MATCH_SCORE", 7):
                body = format_email.format_email_body()

    assert body is not None
    assert "IT Projektų vadovas" in body
    assert "UAB Test" in body
    assert "https://example.com/1" in body
    assert "9/10" in body


def test_format_email_body_html_returns_none_for_empty_list():
    assert format_email.format_email_body_html(jobs=[]) is None


def test_format_email_body_html_renders_valid_structure():
    html = format_email.format_email_body_html(jobs=SAMPLE_JOBS)

    assert html is not None
    assert "<html" in html
    assert "IT Projektų vadovas" in html
    assert "https://example.com/1" in html
    assert "9/10" in html


def test_format_email_body_html_escapes_special_characters():
    """
    SAUGUMAS: patikrina, kad HTML/script turinys skelbimo laukuose (kilęs iš
    scraped trečiosios šalies turinio arba Claude sugeneruoto teksto) yra
    escape'inamas, o ne įterpiamas žaliavine forma - kitaip tai būtų HTML/
    script injection į el. laišką, atidaromą HTML pašto kliente.
    """
    jobs = [
        {
            "title": "Vadovas & Partneris <script>alert(1)</script>",
            "company": "Įmonė <b>Pavojinga</b>",
            "source": "ExampleJobBoard2",
            "url": "https://example.com/2",
            "match_score": 7,
            "match_reason": "Tinka \" onmouseover=\"alert(1)",
        }
    ]

    result = format_email.format_email_body_html(jobs=jobs)

    # Pavojingi tag'ai/atributai NETURI atsirasti neescape'inti
    assert "<script>" not in result
    assert "<b>Pavojinga</b>" not in result
    assert 'onmouseover="alert(1)"' not in result

    # Escape'intos versijos TURI būti tekste (patvirtina, kad turinys išliko,
    # tik saugia forma, o ne tiesiog ištrintas)
    assert "&lt;script&gt;" in result
    assert "&amp;" in result


def test_format_email_body_html_rejects_javascript_url():
    """
    SAUGUMAS: job['url'] kilęs iš scraped turinio - jei kas nors sukurtų
    skelbimą su url="javascript:...", tai NETURI tapti vykdomu href.
    """
    jobs = [{
        "title": "X", "company": "Y", "source": "Z",
        "url": "javascript:alert(document.cookie)",
        "match_score": 7, "match_reason": "...",
    }]

    result = format_email.format_email_body_html(jobs=jobs)

    assert "javascript:" not in result
    assert 'href="#"' in result


def test_format_email_body_html_accepts_valid_https_url():
    jobs = [{
        "title": "X", "company": "Y", "source": "Z",
        "url": "https://example.test/job/1",
        "match_score": 7, "match_reason": "...",
    }]

    result = format_email.format_email_body_html(jobs=jobs)

    assert 'href="https://example.test/job/1"' in result


def test_safe_url_rejects_non_http_schemes():
    assert format_email._safe_url("javascript:alert(1)") == "#"
    assert format_email._safe_url("data:text/html,<script>alert(1)</script>") == "#"
    assert format_email._safe_url("ftp://example.com") == "#"


def test_safe_url_accepts_http_and_https():
    assert format_email._safe_url("https://example.com/job/1") == "https://example.com/job/1"
    assert format_email._safe_url("http://example.com/job/1") == "http://example.com/job/1"


def test_safe_url_handles_none_gracefully():
    """urlparse(None) meta AttributeError - _safe_url turi ją sugauti, ne crash'intis."""
    assert format_email._safe_url(None) == "#"


def test_format_email_body_html_reads_from_file_when_jobs_is_none(tmp_path, monkeypatch):
    """Kai jobs=None, funkcija turi nuskaityti iš config.OUTPUT_FILE, jei jis egzistuoja."""
    import json

    output_file = tmp_path / "matched_jobs.json"
    output_file.write_text(json.dumps([{
        "title": "X", "company": "Y", "source": "Z",
        "url": "https://example.test/1", "match_score": 8, "match_reason": "...",
    }]), encoding="utf-8")

    monkeypatch.setattr(format_email.config, "OUTPUT_FILE", str(output_file))

    result = format_email.format_email_body_html(jobs=None)

    assert result is not None
    assert "https://example.test/1" in result


def test_format_email_body_includes_evidence_when_present():
    jobs = [{
        "title": "IT PM", "company": "Test", "source": "Z",
        "url": "https://example.test/1", "match_score": 9,
        "match_reason": "Puikiai tinka",
        "match_evidence": "Reikalaujama 5+ metų projektų valdymo patirties",
    }]

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = _write_matched_jobs(tmp_dir, jobs)
        with patch.object(format_email.config, "OUTPUT_FILE", path):
            body = format_email.format_email_body()

    assert "Reikalaujama 5+ metų projektų valdymo patirties" in body
    assert "Pagrindimas:" in body


def test_format_email_body_omits_evidence_line_when_absent():
    """Senesni matched_jobs.json be match_evidence lauko neturi lūžti (backward compat)."""
    jobs = [{
        "title": "IT PM", "company": "Test", "source": "Z",
        "url": "https://example.test/1", "match_score": 9,
        "match_reason": "Puikiai tinka",
        # match_evidence tyčia praleistas
    }]

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = _write_matched_jobs(tmp_dir, jobs)
        with patch.object(format_email.config, "OUTPUT_FILE", path):
            body = format_email.format_email_body()

    assert "Pagrindimas:" not in body


def test_format_email_body_html_includes_evidence_when_present():
    jobs = [{
        "title": "IT PM", "company": "Test", "source": "Z",
        "url": "https://example.test/1", "match_score": 9,
        "match_reason": "Puikiai tinka",
        "match_evidence": "Reikalaujama SQL patirtis",
    }]

    result = format_email.format_email_body_html(jobs=jobs)

    assert "Reikalaujama SQL patirtis" in result
    assert "Pagrindimas:" in result


def test_format_email_body_html_omits_evidence_when_absent():
    jobs = [{
        "title": "IT PM", "company": "Test", "source": "Z",
        "url": "https://example.test/1", "match_score": 9,
        "match_reason": "Puikiai tinka",
    }]

    result = format_email.format_email_body_html(jobs=jobs)

    assert "Pagrindimas:" not in result


def test_format_email_body_html_escapes_evidence_field():
    """SAUGUMAS: match_evidence irgi turi būti escape'intas (tas pats XSS rizikos šaltinis)."""
    jobs = [{
        "title": "X", "company": "Y", "source": "Z",
        "url": "https://example.test/1", "match_score": 7,
        "match_reason": "...",
        "match_evidence": "<script>alert(1)</script>",
    }]

    result = format_email.format_email_body_html(jobs=jobs)

    assert "<script>alert(1)</script>" not in result
    assert "&lt;script&gt;" in result
