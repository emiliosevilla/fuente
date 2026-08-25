from pathlib import Path


CONSOLE = Path(__file__).resolve().parent.parent / "consola_preview.html"
CSS = Path(__file__).resolve().parent.parent / "fuente/ui/static/console.css"


def _source() -> str:
    return CONSOLE.read_text(encoding="utf-8")


def test_theme_control_is_custom_accessible_and_not_native_select():
    source = _source()

    assert '<select id="theme-select"' not in source
    assert 'id="theme-select-trigger"' in source
    assert 'aria-haspopup="listbox"' in source
    assert 'aria-controls="theme-select-menu"' in source
    assert 'id="theme-select-menu"' in source
    assert 'role="listbox"' in source
    assert "handleThemeTriggerKeydown(event)" in source
    assert "event.key === 'Enter'" in source
    assert "event.key === ' '" in source
    assert "event.key === 'ArrowDown'" in source
    assert "event.key === 'ArrowUp'" in source
    assert "event.key === 'Escape'" in source
    assert "handleThemeOptionKeydown(event)" in source
    assert "event.currentTarget.click()" in source
    assert "!themeControl.contains(event.target)" in source


def test_theme_selection_paints_before_bridge_and_reverts_on_failure():
    source = _source()

    visual_update = source.index("currentActiveTheme = themeName;", source.index("function changeActiveTheme"))
    render_update = source.index("renderThemeSelect();", visual_update)
    bridge_call = source.index("set_theme(themeName)", render_update)
    assert visual_update < render_update < bridge_call
    assert "currentActiveTheme = previousTheme;" in source
    assert ".catch(function(error)" in source
    assert "res && res.error" in source
    assert "themeChangeRequest" in source
    assert "if (requestId !== themeChangeRequest) return;" in source


def test_reader_chat_context_buttons_have_exclusive_semantic_state():
    source = _source()

    assert "button.dataset.chatContextMode = action[0]" in source
    assert "button.setAttribute('aria-pressed', 'false')" in source
    assert "function syncChatContextButtons()" in source
    assert "button.classList.toggle('active', isActive)" in source
    assert "button.setAttribute('aria-pressed', String(isActive))" in source
    assert "syncChatContextButtons();" in source
    assert "data-chat-context-mode" in source


def test_ui1_styles_define_open_menu_focus_and_active_states():
    css = CSS.read_text(encoding="utf-8")

    assert ".theme-select-menu.is-open" in css
    assert ".theme-select-trigger:hover" in css
    assert "background: var(--bg-card-hover)" in css
    assert "transform: translateY(-1px)" in css
    assert "box-shadow: var(--elevation-low)" in css
    assert ".theme-select-trigger:focus-visible" in css
    assert ".theme-select-option:hover" in css
    assert ".console-layout-073.active" in css
