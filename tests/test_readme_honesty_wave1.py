"""README claims must match the current Gestajo-first workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8").lower()


def test_readme_assigns_document_interaction_to_gestajo():
    assert "gestajo es la interfaz" in README
    assert "lectura, edición y grafo" in README
    assert "operación documental cotidiana se realiza dentro de gestajo" in README


def test_readme_documents_the_manual_capture_to_processing_boundary():
    assert "3_capturado" in README
    assert "4_procesado" in README
    assert "no es automático" in README
    assert "plantilla de nota concreta" in README


def test_readme_keeps_cloud_integrations_outside_the_local_boundary():
    assert "no hay credenciales cloud" in README
    assert "ollama usa loopback" in README
    assert "anythingllm" in README


def test_readme_documents_the_local_gestajo_agent_contract():
    assert "https://127.0.0.1:43819" in README
    assert "no ofrece un api público" in README
    assert "publica sólo metadatos" in README
    assert "nuevos o cambiados" in README
