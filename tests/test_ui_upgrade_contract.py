"""Acceptance contracts for the Fuente native workspace redesign."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "consola_preview.html").read_text(encoding="utf-8")
CSS = (ROOT / "fuente/ui/static/console.css").read_text(encoding="utf-8")
TOKENS = (ROOT / "fuente/ui/static/fuente_tokens.css").read_text(encoding="utf-8")


def test_native_shell_has_three_product_workspaces_and_one_main_region():
    assert 'id="primary-navigation"' in HTML
    assert 'aria-label="Espacios de Fuente y Caudal"' in HTML
    for workspace in ("home", "source", "flow"):
        assert f'data-workspace-target="{workspace}"' in HTML
        assert f'id="workspace-{workspace}"' in HTML
    assert re.findall(r'data-workspace="([^"]+)"', HTML) == ["home", "source", "flow"]
    assert "Meetily" not in HTML
    assert "meetily" not in HTML.lower()
    assert "meeting-" not in CSS
    assert HTML.count('role="main"') == 1


def test_home_is_command_dashboard_not_product_gate():
    assert 'id="home-product-access"' in HTML
    assert 'id="home-dashboard-title"' in HTML
    assert "Estado general" in HTML
    assert 'class="stats-grid"' not in HTML
    assert 'class="stat-card"' not in HTML
    home = HTML.split('id="home-product-access"', 1)[1].split("</section>", 1)[0]
    assert "Abrir Fuente" not in home
    assert "Abrir Caudal" not in home
    assert "Elige dónde trabajar" not in home
    assert 'data-onclick-command="switchWorkspace(\'source\')"' in HTML
    assert 'data-onclick-command="switchWorkspace(\'flow\')"' in HTML


def test_caudal_spine_has_exactly_five_named_cells():
    assert re.findall(r'data-flow-step="([1-5])"', HTML) == ["1", "2", "3", "4", "5"]
    assert HTML.count('class="flow-stage"') == 5
    for label in ("Volcado", "Copiado", "Capturado", "Procesado", "Compartido"):
        assert label in HTML


def test_component_css_uses_semantic_tokens_and_reduced_motion():
    assert "var(--surface-canvas)" in CSS
    assert "var(--text-primary)" in CSS
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    assert not re.search(r"#[0-9a-fA-F]{6}", CSS)
    for token in (
        "--surface-canvas",
        "--surface-raised",
        "--text-primary",
        "--text-secondary",
        "--accent-primary",
        "--focus-ring",
    ):
        assert f"{token}:" in TOKENS


def test_primary_navigation_is_semantic_and_icon_controls_are_named():
    assert '<nav id="primary-navigation"' in HTML
    icon_buttons = re.findall(r'<button(?=[^>]*class="[^"]*icon-button)[^>]*>', HTML)
    assert icon_buttons
    assert all("aria-label=" in button for button in icon_buttons)


def test_settings_is_a_utility_and_not_a_fourth_workspace():
    navigation = HTML.split('<nav id="primary-navigation"', 1)[1].split("</nav>", 1)[0]
    assert 'data-onclick-command="openModal(\'modal-settings\')"' in navigation
    assert 'data-workspace-target="settings"' not in HTML
    assert 'data-workspace="settings"' not in HTML


def test_dialog_controller_restores_focus_and_handles_escape():
    assert "lastDialogTrigger" in HTML
    assert "lastDialogTrigger.focus()" in HTML
    assert "event.key === 'Escape'" in HTML
    assert "getFocusableElements" in HTML
