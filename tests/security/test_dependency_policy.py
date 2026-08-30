"""Security policy regressions for direct production dependencies."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MINIRAG_PIN = "minirag-hku @ git+https://github.com/HKUDS/MiniRAG.git@e204d239421f45004852953679927fdf6733f236"
LANCEDB_PIN = "lancedb==0.37.1"


def test_lancedb_is_the_primary_vector_backend_and_minirag_stays_available_for_rollback() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert MINIRAG_PIN in requirements
    assert f'"{MINIRAG_PIN}"' in pyproject
    assert LANCEDB_PIN in requirements
    assert f'"{LANCEDB_PIN}"' in pyproject
    assert "chromadb" not in requirements
    assert "chromadb" not in pyproject
