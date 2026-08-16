from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fuente.extractors.ocr_runtime import (
    FallbackOCR,
    OCRWord,
    TesseractOCR,
    render_ocr_layout,
)
from fuente.extractors.macos_vision import MacOSVisionOCR
from fuente.extractors.registry import build_ocr_backend
from fuente.installer_contract import (
    InstallationContext,
    detect_ocr_status,
    run_installation,
)


def test_tesseract_ocr_uses_both_required_languages(monkeypatch, tmp_path):
    image = tmp_path / "certificado.png"
    image.write_bytes(b"image")
    fake_image = MagicMock()
    fake_image.__enter__.return_value = fake_image
    fake_image.__exit__.return_value = False
    fake_module = SimpleNamespace(
        pytesseract=SimpleNamespace(tesseract_cmd=""),
        image_to_string=MagicMock(return_value="Texto reconocido"),
    )
    monkeypatch.setitem(__import__("sys").modules, "pytesseract", fake_module)
    monkeypatch.setitem(__import__("sys").modules, "PIL", SimpleNamespace(Image=SimpleNamespace(open=MagicMock(return_value=fake_image))))

    backend = TesseractOCR(
        command=Path("/usr/local/bin/tesseract"),
        image_to_string=fake_module.image_to_string,
    )
    assert backend.extract_image(image) == "Texto reconocido"
    fake_image.convert.assert_called_once_with("RGB")
    fake_module.image_to_string.assert_called_once()
    assert fake_module.image_to_string.call_args.kwargs["lang"] == "eng+spa"


def test_fallback_ocr_uses_tesseract_after_macos_vision_fails():
    primary = SimpleNamespace(
        method="macos_vision",
        extract_image=lambda _path: (_ for _ in ()).throw(RuntimeError("Vision falló")),
    )
    fallback = SimpleNamespace(method="tesseract", extract_image=lambda _path: "texto")

    backend = FallbackOCR(primary, fallback)
    assert backend.extract_image(Path("imagen.jpg")) == "texto"
    assert backend.last_method == "tesseract"


def test_layout_renderer_reconstructs_generic_table_without_domain_labels():
    words = [
        OCRWord("Item", 100, 100, 40, 18, "header"),
        OCRWord("Units", 300, 100, 48, 18, "header"),
        OCRWord("Cost", 500, 100, 38, 18, "header"),
        OCRWord("Notebook", 100, 140, 80, 18, "row-1"),
        OCRWord("2", 300, 140, 12, 18, "row-1"),
        OCRWord("10.00", 500, 140, 45, 18, "row-1"),
        OCRWord("Pen", 100, 180, 28, 18, "row-2"),
        OCRWord("5", 300, 180, 12, 18, "row-2"),
        OCRWord("1.50", 500, 180, 35, 18, "row-2"),
    ]

    rendered = render_ocr_layout(words)

    assert "| Item | Units | Cost |" in rendered
    assert "| Notebook | 2 | 10.00 |" in rendered
    assert "| Pen | 5 | 1.50 |" in rendered


def test_tesseract_uses_layout_data_for_generic_tables(tmp_path, monkeypatch):
    image = tmp_path / "table.png"
    image.write_bytes(b"image")
    fake_image = MagicMock()
    fake_image.__enter__.return_value = fake_image
    fake_image.__exit__.return_value = False
    fake_image.size = (800, 400)
    data = {
        "text": ["Item", "Units", "Cost", "Notebook", "2", "10.00", "Pen", "5", "1.50"],
        "left": [100, 300, 500, 100, 300, 500, 100, 300, 500],
        "top": [100, 100, 100, 140, 140, 140, 180, 180, 180],
        "width": [40, 48, 38, 80, 12, 45, 28, 12, 35],
        "height": [18, 18, 18, 18, 18, 18, 18, 18, 18],
        "conf": [95, 95, 95, 95, 95, 95, 95, 95, 95],
        "block_num": [1, 1, 1, 1, 1, 1, 1, 1, 1],
        "par_num": [1, 1, 1, 1, 1, 1, 1, 1, 1],
        "line_num": [1, 1, 1, 2, 2, 2, 3, 3, 3],
    }
    fake_module = SimpleNamespace(
        pytesseract=SimpleNamespace(tesseract_cmd=""),
        image_to_string=MagicMock(return_value="texto plano"),
    )
    backend = TesseractOCR(
        command=Path("/usr/local/bin/tesseract"),
        image_to_string=fake_module.image_to_string,
        image_to_data=MagicMock(return_value=data),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "PIL",
        SimpleNamespace(Image=SimpleNamespace(open=MagicMock(return_value=fake_image))),
    )

    assert "| Item | Units | Cost |" in backend.extract_image(image)


def test_layout_renderer_keeps_non_table_text_as_text():
    words = [
        OCRWord("Texto", 100, 100, 40, 18, "paragraph"),
        OCRWord("normal", 150, 100, 52, 18, "paragraph"),
    ]

    rendered = render_ocr_layout(words)

    assert rendered == "Texto normal"


def test_registry_uses_tesseract_as_primary_backend_on_windows(monkeypatch):
    backend = build_ocr_backend(platform="win32")

    assert isinstance(backend, TesseractOCR)


def test_registry_uses_layout_aware_tesseract_first_on_macos(monkeypatch):
    monkeypatch.setattr(TesseractOCR, "available", lambda _self: True)

    backend = build_ocr_backend(platform="darwin")

    assert isinstance(backend, FallbackOCR)
    assert isinstance(backend.primary, TesseractOCR)
    assert isinstance(backend.fallback, MacOSVisionOCR)


def test_ocr_setup_is_an_explicit_installation_step(tmp_path, monkeypatch):
    ctx = InstallationContext(
        base_dir=tmp_path,
        vault_path=tmp_path / "Fuente",
        confirm=lambda _title, _message: False,
        install_model=False,
        install_ocr=True,
        install_anythingllm=False,
        configure_anythingllm=False,
        create_shortcuts=False,
    )
    monkeypatch.setattr(
        "fuente.installer_contract.detect_ocr_status",
        lambda: SimpleNamespace(
            ready=False,
            summary="Tesseract no está instalado",
            command=None,
            languages=frozenset(),
            missing_languages=frozenset({"eng", "spa"}),
        ),
    )

    results = run_installation(ctx)
    ocr_step = next(step for step in results if step.name == "ocr_runtime")

    assert ocr_step.success is False
    assert ocr_step.actionable


def test_detect_ocr_status_reports_required_languages(monkeypatch):
    monkeypatch.setattr(
        "fuente.installer_contract.resolve_tesseract_command",
        lambda: "/usr/local/bin/tesseract",
    )
    monkeypatch.setattr(
        "fuente.installer_contract.list_tesseract_languages",
        lambda _command: {"eng"},
    )

    status = detect_ocr_status()

    assert status.ready is False
    assert "spa" in status.missing_languages
