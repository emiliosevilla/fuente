"""Security policy regressions for direct production dependencies."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SAFE_CHROMADB_PIN = "chromadb==0.6.3"


def test_chromadb_pin_excludes_cve_2026_45829_range() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert SAFE_CHROMADB_PIN in requirements
    assert f'"{SAFE_CHROMADB_PIN}"' in pyproject
    assert "chromadb==1.5.9" not in requirements
    assert '"chromadb~=1.5.0"' not in pyproject
