"""Contracts for the Fuente and Caudal native product shell."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "consola_preview.html"
CONSOLE_CSS_PATH = ROOT / "fuente/ui/static/console.css"
TOKENS_CSS_PATH = ROOT / "fuente/ui/static/fuente_tokens.css"
FUENTE_TOKENS = ("--fuente-polar-0", "--fuente-polar-1", "--fuente-polar-2", "--fuente-snow-2", "--fuente-snow-0", "--fuente-frost-2", "--fuente-frost-1", "--fuente-success", "--fuente-warning", "--fuente-danger")

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def _hex_rgb(value: str) -> tuple[float, float, float]:
    value = value.removeprefix("#")
    return tuple(int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))

def _relative_luminance(value: str) -> float:
    channels = tuple(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in _hex_rgb(value))
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

def _contrast_ratio(first: str, second: str) -> float:
    light, dark = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)

def _token_hex(tokens_css: str, token: str) -> str:
    match = re.search(rf"{re.escape(token)}\s*:\s*(#[0-9A-Fa-f]{{6}})", tokens_css)
    assert match is not None
    return match.group(1)

def _theme_token_hex(tokens_css: str, theme: str, token: str) -> str:
    block = re.search(rf'html\[data-fuente-style="{theme}"\]\s*\{{(.*?)\n\}}', tokens_css, re.DOTALL)
    assert block is not None
    return _token_hex(block.group(1), token)

def test_fuente_tokens_file_declares_semantic_nord_tokens() -> None:
    tokens_css = _read(TOKENS_CSS_PATH)
    for token in FUENTE_TOKENS:
        assert re.search(rf"{re.escape(token)}\s*:", tokens_css)

def test_console_loads_local_fuente_tokens_before_console_css() -> None:
    html = _read(HTML_PATH)
    links = re.findall(r'<link\s+[^>]*rel=["\']stylesheet["\'][^>]*href=["\']([^"\']+)', html, flags=re.IGNORECASE)
    assert "fuente/ui/static/fuente_tokens.css" in links
    assert "fuente/ui/static/console.css" in links
    assert links.index("fuente/ui/static/fuente_tokens.css") < links.index("fuente/ui/static/console.css")
    assert TOKENS_CSS_PATH.is_file()

def test_console_consumes_fuente_tokens_instead_of_literal_nord_palette() -> None:
    css = _read(CONSOLE_CSS_PATH)
    assert "var(--fuente-" in css
    nord_hex_values = ("#2E3440", "#3B4252", "#434C5E", "#D8DEE9", "#E5E9F0", "#ECEFF4", "#8FBCBB", "#88C0D0", "#81A1C1", "#5E81AC", "#A3BE8C", "#EBCB8B", "#BF616A")
    assert not any(value in css.upper() for value in nord_hex_values)

def test_caudal_shell_exposes_five_non_empty_stages_and_reduced_motion() -> None:
    html, css, tokens = _read(HTML_PATH), _read(CONSOLE_CSS_PATH), _read(TOKENS_CSS_PATH)
    assert re.findall(r'data-flow-step="([1-5])"', html) == ["1", "2", "3", "4", "5"]
    for label in ("Volcado", "Copiado", "Capturado", "Procesado", "Compartido"):
        assert label in html
    assert all(f'id="badge-step{step}"' in html for step in range(1, 6))
    assert "═►" not in html
    assert "--fuente-glass:" in tokens
    assert "--fuente-shadow-glass:" in tokens
    assert "prefers-reduced-motion" in css

def test_console_exposes_independent_nord_gruvbox_visual_style_toggle() -> None:
    html = _read(HTML_PATH)
    assert '<html lang="es" data-fuente-style="nord">' in html
    assert 'id="style-toggle"' in html
    assert '<span id="style-toggle-label">Gruvbox</span>' in html
    assert "const nextStyle = activeStyle === 'nord' ? 'gruvbox' : 'nord'" in html
    assert "const nextStyleLabel = nextStyle === 'gruvbox' ? 'Gruvbox' : 'Nord'" in html
    assert "styleLabel.textContent = nextStyleLabel" in html
    assert "styleToggle.setAttribute('aria-pressed'" not in html
    assert "document.documentElement.dataset.fuenteStyle = activeStyle" in html
    assert "persistUiState('main-window', 'visual_style', activeStyle)" in html
    assert "localStorage.getItem" not in html
    assert "localStorage.setItem" not in html
    assert "localStorage.removeItem('fuente.visual-style')" in html
    assert "function toggleVisualStyle()" in html
    assert "'toggleVisualStyle()': toggleVisualStyle" in html

def test_nord_and_gruvbox_text_tokens_meet_normal_text_contrast() -> None:
    tokens = _read(TOKENS_CSS_PATH)
    for theme in ("nord", "gruvbox"):
        canvas = _theme_token_hex(tokens, theme, "--surface-canvas")
        for token in (
            "--text-primary",
            "--text-secondary",
            "--accent-primary",
            "--state-success",
            "--state-warning",
            "--state-danger",
        ):
            assert _contrast_ratio(canvas, _theme_token_hex(tokens, theme, token)) >= 4.5
        assert _contrast_ratio(canvas, _theme_token_hex(tokens, theme, "--focus-ring")) >= 3

def test_nord_is_the_light_initial_theme() -> None:
    tokens = _read(TOKENS_CSS_PATH)
    assert _theme_token_hex(tokens, "nord", "--surface-canvas").upper() == "#ECEFF4"
    assert _theme_token_hex(tokens, "nord", "--surface-raised").upper() == "#FFFFFF"
    assert _theme_token_hex(tokens, "nord", "--text-primary").upper() == "#2E3440"

def test_visual_style_toggle_does_not_reuse_vault_theme_bridge() -> None:
    html = _read(HTML_PATH)
    style_change, vault_theme_bridge = html.index("function toggleVisualStyle()"), html.index("set_theme(themeName)")
    assert style_change < vault_theme_bridge
    assert "applyVisualStyle(currentStyle === 'nord' ? 'gruvbox' : 'nord')" in html
    assert 'id="style-select"' not in html
    assert 'id="settings-style-select"' not in html

def test_reader_exposes_read_only_content_and_properties() -> None:
    html = _read(HTML_PATH)
    for region in ("content", "properties"):
        assert f'data-reader-region="{region}"' in html
    assert 'id="reader-properties"' in html
    assert "function renderReaderProperties(" in html

def test_console_reader_css_keeps_keyboard_focus_and_narrow_layout() -> None:
    css = _read(CONSOLE_CSS_PATH)
    assert ":focus-visible" in css
    assert re.search(r"@media\s*[^{}]*max-width\s*:", css)

def test_shell_has_exactly_three_product_workspaces() -> None:
    html = _read(HTML_PATH)
    assert re.findall(r'data-workspace="([^"]+)"', html) == ["home", "source", "flow"]
    assert re.findall(r'data-workspace-target="([^"]+)"', html) == ["home", "source", "flow"]
    assert 'aria-label="Espacios de Fuente y Caudal"' in html
    assert html.count('role="main"') == 1

def test_shell_dimensions_type_and_keyboard_focus_are_explicit() -> None:
    html, css, tokens = _read(HTML_PATH), _read(CONSOLE_CSS_PATH), _read(TOKENS_CSS_PATH)
    for declaration in (
        "--rail-width: 113px",
        "--header-height: 72px",
        "--font-size-base: 16px",
        "--font-size-document: 17px",
        "--font-size-control: 14px",
    ):
        assert declaration in tokens
    assert "height: var(--header-height)" in css
    assert "overflow-x: hidden" in css
    assert 'id="workspace-home-title" tabindex="-1"' in html
    assert 'id="workspace-source-title" tabindex="-1"' in html
    assert 'id="workspace-flow-title" tabindex="-1"' in html
    assert "document.querySelector('#workspace-' + workspaceId + ' h1')" in html
    assert "heading.focus({preventScroll: true})" in html
    assert "document.activeElement.setAttribute('data-keyboard-focus', 'true')" in html
    assert '[data-keyboard-focus="true"]' in css

def test_shell_uses_named_svg_controls_and_shared_disclosures() -> None:
    html = _read(HTML_PATH)
    navigation = html.split('<nav id="primary-navigation"', 1)[1].split("</nav>", 1)[0]
    assert navigation.count("<svg") >= 5
    assert '<span aria-hidden="true">F</span>' not in navigation
    assert '<span aria-hidden="true">N</span>' not in navigation
    for primitive in ("ui-drawer", "ui-popover", "ui-accordion", "ui-carousel"):
        assert primitive in html
    assert 'id="source-context-drawer"' in html
    assert 'id="flow-detail-drawer"' in html
    assert 'aria-hidden="true"' in html.split('id="source-context-drawer"', 1)[1].split(">", 1)[0]
    assert 'aria-hidden="true"' in html.split('id="flow-detail-drawer"', 1)[1].split(">", 1)[0]


def test_structural_controls_use_shared_svg_icons_beyond_the_rail() -> None:
    html = _read(HTML_PATH)
    for glyph in ("◄", "⌕", "×", "&times;"):
        assert glyph not in html
    assert 'id="ui-icon-definitions"' in html
    assert 'id="ui-icon-back"' in html
    assert 'id="ui-icon-search"' in html
    assert 'id="ui-icon-close"' in html
    assert html.count('class="ui-icon"') >= 16
    assert "createUiIcon('close')" in html

def test_reader_rendering_does_not_add_innerhtml_assignments() -> None:
    html = _read(HTML_PATH)
    assert re.search(r"\.innerHTML\s*=", html) is None
    assert re.search(r"(?:readerContent|readerProperties|readerRelations)\.innerHTML\s*=", html) is None

def test_upgrade_palette_is_semantic_and_component_css_has_no_hex_literals() -> None:
    css, tokens = _read(CONSOLE_CSS_PATH), _read(TOKENS_CSS_PATH)
    for token in (
        "--surface-canvas",
        "--surface-raised",
        "--surface-sunken",
        "--surface-overlay",
        "--text-primary",
        "--text-secondary",
        "--border-subtle",
        "--accent-primary",
        "--accent-selection",
        "--focus-ring",
        "--state-success",
        "--state-warning",
        "--state-danger",
    ):
        assert f"{token}:" in tokens
    assert re.search(r"#[0-9a-fA-F]{6}", css) is None


def test_fuente_mockup_identity_markers_are_present() -> None:
    html = _read(HTML_PATH)
    assert "Arquitectura local" in html
    assert "Solo lectura" in html
    assert "Objetivo" in html
    assert "Principios" in html
    assert "Componentes" in html
    assert "Limpiar filtros" in html
    assert 'name="source-filter-seal"' in html
    assert 'type="checkbox"' in html
    assert "Índice de contenido con ChromaDB" in html
    assert "Principios de diseño" in html
    assert "Flujo de consulta local" in html
    assert "\u2014" not in html
    assert "\u2013" not in html
    assert "Detalle del archivo" in html
    assert "Contrato_Servicios_v3.docx" in html
    assert "function applyCaptureScenario(name)" in html
    assert "switchSourceView('individual')" in html.split("source-view-modes", 1)[1]
    assert "source-filter-drawer" in html.split("source-view-modes", 1)[1]
    assert "restoreCaudalQueueFixture" in html
    assert "caudal-queue-fixture" in html
    assert "if (document.body.getAttribute('data-capture-scenario')) return;" in html
    assert 'id="aux-search-relations"' in html
    assert "Decisiones de arquitectura - Q1 2025" in html
    assert "Contenido: ChromaDB" in html
    assert "modal-caudal-import" in html
    assert "Elegir..." in html
    assert "if (id === 'modal-template-helper' && !document.body.getAttribute('data-capture-scenario'))" in html
    assert "openModal('modal-caudal-import')" in html.split("flow-1024", 1)[1]
    assert "aux-search-relations" in html.split("source-search-relations", 1)[1]
