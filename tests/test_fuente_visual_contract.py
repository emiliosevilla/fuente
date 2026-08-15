"""Red contracts for Task 9's Fuente visual system and reader layout."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "consola_preview.html"
CONSOLE_CSS_PATH = ROOT / "fuente/ui/static/console.css"
TOKENS_CSS_PATH = ROOT / "fuente/ui/static/fuente_tokens.css"

FUENTE_TOKENS = (
    "--fuente-polar-0",
    "--fuente-polar-1",
    "--fuente-polar-2",
    "--fuente-snow-2",
    "--fuente-snow-0",
    "--fuente-frost-2",
    "--fuente-frost-1",
    "--fuente-success",
    "--fuente-warning",
    "--fuente-danger",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_fuente_tokens_file_declares_semantic_nord_tokens() -> None:
    tokens_css = _read(TOKENS_CSS_PATH)

    for token in FUENTE_TOKENS:
        assert re.search(rf"{re.escape(token)}\s*:", tokens_css)


def test_console_loads_local_fuente_tokens_before_console_css() -> None:
    html = _read(HTML_PATH)
    links = re.findall(
        r'<link\s+[^>]*rel=["\']stylesheet["\'][^>]*href=["\']([^"\']+)',
        html,
        flags=re.IGNORECASE,
    )

    assert "fuente/ui/static/fuente_tokens.css" in links
    assert "fuente/ui/static/console.css" in links
    assert links.index("fuente/ui/static/fuente_tokens.css") < links.index(
        "fuente/ui/static/console.css"
    )
    assert TOKENS_CSS_PATH.is_file()


def test_console_consumes_fuente_tokens_instead_of_literal_nord_palette() -> None:
    css = _read(CONSOLE_CSS_PATH)

    assert "var(--fuente-" in css
    nord_hex_values = (
        "#2E3440",
        "#3B4252",
        "#434C5E",
        "#D8DEE9",
        "#E5E9F0",
        "#ECEFF4",
        "#8FBCBB",
        "#88C0D0",
        "#81A1C1",
        "#5E81AC",
        "#A3BE8C",
        "#EBCB8B",
        "#BF616A",
    )
    assert not any(value in css.upper() for value in nord_hex_values)


def test_reader_exposes_content_properties_and_relations_regions() -> None:
    html = _read(HTML_PATH)

    for region in ("content", "properties", "relations"):
        assert f'data-reader-region="{region}"' in html
    assert 'id="reader-properties"' in html
    assert "function renderReaderProperties(" in html
    assert "loadObsidianGraphView();" in html


def test_console_reader_css_keeps_keyboard_focus_and_narrow_layout() -> None:
    css = _read(CONSOLE_CSS_PATH)

    assert ":focus-visible" in css
    assert re.search(r"@media\s*[^{}]*max-width\s*:", css)


def test_reader_rendering_does_not_add_innerhtml_assignments() -> None:
    html = _read(HTML_PATH)

    assert re.search(r"\.innerHTML\s*=", html) is None
    assert re.search(
        r"(?:readerContent|readerProperties|readerRelations)\.innerHTML\s*=",
        html,
    ) is None


def test_reader_views_keep_hidden_state_and_canvas_uses_a_semantic_token() -> None:
    html = _read(HTML_PATH)
    css = _read(CONSOLE_CSS_PATH)

    assert "reader-graph-container.is-hidden" in css
    assert "reader-context-content #reader-view-list.is-hidden" in css
    assert "getPropertyValue('--fuente-snow-0')" in html
    assert "ctx.fillStyle = '#5E564B'" not in html
