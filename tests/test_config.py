"""Testai config.py numatytiesiems (fallback) atvejams, kai env kintamieji nenustatyti."""

import importlib
import sys

import config


def test_get_keywords_returns_demo_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("SEARCH_KEYWORDS", raising=False)
    result = config._get_keywords()
    assert result == ["projektu vadovas", "product owner"]


def test_get_keywords_parses_env_when_set(monkeypatch):
    monkeypatch.setenv("SEARCH_KEYWORDS", "a, b ,c")
    result = config._get_keywords()
    assert result == ["a", "b", "c"]


def test_get_profile_returns_demo_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("CANDIDATE_PROFILE", raising=False)
    result = config._get_profile()
    assert "Pavyzdinis kandidato profilis" in result


def test_module_survives_missing_dotenv_dependency(monkeypatch):
    """
    Patikrina, kad config.py neluš, jei python-dotenv nėra įdiegtas
    (produkcijoje/GitHub Actions dotenv nebūtinas - žr. modulio docstring).
    Simuliuojama pašalinant 'dotenv' iš sys.modules ir priverčiant import
    kelti ImportError, tada iš naujo importuojant config.py.
    """
    monkeypatch.setitem(sys.modules, "dotenv", None)  # None sys.modules reikšmė priverčia ImportError
    try:
        importlib.reload(config)
    finally:
        importlib.reload(config)  # sugrąžiname normalią būseną kitiems testams
