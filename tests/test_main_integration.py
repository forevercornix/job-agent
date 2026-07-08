"""
Integracinis testas: patikrina, kad main.py grąžina TEISINGĄ exit code
operacinei sistemai/CI, priklausomai nuo RunManifest statuso.

Tai svarbu, nes GitHub Actions (ar bet kuris kitas CI/cron) sprendžia
"pavyko/nepavyko" pagal exit code, ne pagal tai, ką skriptas atspausdino
terminale. Be teisingo exit code, kritinė preflight klaida atrodytų kaip
sėkmingas paleidimas (žalia varnelė), nors realiai agentas nepasileido.
"""

import subprocess
import sys


def test_main_exits_nonzero_when_preflight_fails(tmp_path, monkeypatch):
    """
    Paleidžia main.py atskirame procese BE ANTHROPIC_API_KEY - preflight
    turi nepavykti, ir procesas turi grąžinti exit code != 0.
    """
    import os
    import shutil

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Nukopijuojame reikalingus modulius į izoliuotą tmp_path, kad testas
    # nepaliktų pėdsakų (seen_jobs.json ir pan.) tikrame repo kataloge.
    for fname in ("main.py", "manifest.py", "ranker.py", "scraper.py",
                  "deduplicator.py", "config.py", "sources.yaml",
                  "circuit_breaker.py", "logging_config.py"):
        shutil.copy(os.path.join(repo_root, fname), tmp_path / fname)

    # schemas/ katalogas irgi reikalingas - ranker.py įkelia
    # schemas/rank_result.schema.json santykiniu keliu nuo savo failo vietos.
    shutil.copytree(os.path.join(repo_root, "schemas"), tmp_path / "schemas")

    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env["SEARCH_KEYWORDS"] = "test"
    env["CANDIDATE_PROFILE"] = "test profile"

    result = subprocess.run(
        [sys.executable, "main.py"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0, (
        f"main.py turėjo grąžinti ne-nulinį exit code, kai preflight nepavyksta. "
        f"stdout: {result.stdout}"
    )
    assert "preflight_failed" in result.stdout or "KRITINĖ KLAIDA" in result.stdout
