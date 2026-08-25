"""Acceptance contracts for the Fuente native workspace redesign."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "consola_preview.html").read_text(encoding="utf-8")
CSS = (ROOT / "fuente/ui/static/console.css").read_text(encoding="utf-8")
TOKENS = (ROOT / "fuente/ui/static/fuente_tokens.css").read_text(encoding="utf-8")


def test_native_shell_has_four_primary_workspaces_and_one_main_region():
    assert 'id="primary-navigation"' in HTML
    assert 'aria-label="Espacios de Fuente"' in HTML
    for workspace in ("home", "notes", "meetings", "map"):
        assert f'data-workspace-target="{workspace}"' in HTML
        assert f'id="workspace-{workspace}"' in HTML
    assert HTML.count('role="main"') == 1


def test_home_is_not_a_uniform_stat_card_dashboard():
    assert 'class="stats-grid"' not in HTML
    assert 'class="stat-card"' not in HTML
    assert 'id="fuente-flow"' in HTML
    assert all(f'id="badge-step{step}"' in HTML for step in range(1, 6))


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


def test_dialog_controller_restores_focus_and_handles_escape():
    assert "lastDialogTrigger" in HTML
    assert "lastDialogTrigger.focus()" in HTML
    assert "event.key === 'Escape'" in HTML
    assert "getFocusableElements" in HTML
