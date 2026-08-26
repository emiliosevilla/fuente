"""Q-03 contracts for visible PyWebView recovery states."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "consola_preview.html").read_text(encoding="utf-8")
MAIN_SOURCE = (ROOT / "fuente" / "main.py").read_text(encoding="utf-8")
LAUNCHER_SOURCE = (ROOT / "fuente" / "control_console.py").read_text(
    encoding="utf-8"
)
SETUP_SOURCE = (ROOT / "fuente" / "ui" / "setup_backend.py").read_text(
    encoding="utf-8"
)
BRIDGE_SOURCE = (ROOT / "fuente" / "ui" / "bridge.py").read_text(
    encoding="utf-8"
)


def _function_source(name: str, next_name: str) -> str:
    start = SOURCE.index(f"function {name}")
    end = SOURCE.index(f"function {next_name}", start)
    return SOURCE[start:end]


def test_reader_list_rejection_and_malformed_payload_render_visible_error():
    loader = _function_source("loadReaderNotes", "highlightSidebarNote")

    assert "Array.isArray(notes)" in loader
    assert "renderReaderLoadError(" in loader
    assert ".catch(function(err)" in loader
    assert "log(" in _function_source("renderReaderLoadError", "renderReaderContentError")


def test_pywebview_ready_recovers_open_reader_and_settings_modals():
    recovery = _function_source("recoverNativeModalLoads", "openModal")
    ready_start = SOURCE.index("window.addEventListener('pywebviewready'")
    ready_end = SOURCE.index("document.addEventListener('DOMContentLoaded'", ready_start)
    ready_listener = SOURCE[ready_start:ready_end]

    assert "window.pywebview.api" in recovery
    assert "modal-reader" in recovery
    assert "modal-settings" in recovery
    assert recovery.count("classList.contains('is-open')") == 2
    assert "loadReaderNotes();" in recovery
    assert "loadSettingsData();" in recovery
    assert "recoverNativeModalLoads();" in ready_listener
    assert "if (nativeConsoleInitialized) return;" in ready_listener
    assert "nativeConsoleInitialized = true;" in ready_listener
    assert "clearTimeout(nativeReadyTimer);" in ready_listener
    assert "nativeReadyTimer = setTimeout(function()" in ready_listener
    assert "NATIVE_INITIAL_STATE_TIMEOUT_MS" in ready_listener
    assert "}, NATIVE_INITIAL_STATE_TIMEOUT_MS).then(function(state)" in ready_listener


def test_console_csp_allows_pywebview_62_to_build_native_api_methods():
    csp = next(
        line for line in SOURCE.splitlines() if "Content-Security-Policy" in line
    )
    script_policy = csp.split("script-src", 1)[1].split(";", 1)[0]

    # PyWebView 6.2 creates js_api wrappers with new Function(...).
    assert "'unsafe-eval'" in script_policy


def test_static_preview_is_explicit_and_native_loads_fail_visibly():
    preview_mode = _function_source(
        "isExplicitPreviewMode", "nativeBackendUnavailableMessage"
    )
    native_request = _function_source("callNativeRequest", "recoverNativeModalLoads")
    reader = _function_source("loadReaderNotes", "highlightSidebarNote")
    content = _function_source("loadNoteContent", "loadCategoryData")
    settings = _function_source("loadSettingsData", "showButtonFeedback")

    assert "new URLSearchParams(window.location.search)" in preview_mode
    assert "params.get('preview') === 'mock'" in preview_mode
    assert "typeof api[methodName] !== 'function'" in native_request
    assert "Promise.resolve().then" in native_request
    assert "Promise.race" in native_request
    assert "setTimeout(function()" in native_request
    assert reader.index("isExplicitPreviewMode()") < reader.index("LOCAL_MOCK_NOTES")
    assert "callNativeRequest('get_notes_list'" in reader
    assert content.index("isExplicitPreviewMode()") < content.index("LOCAL_MOCK_NOTES")
    assert "callNativeRequest('get_note_content'" in content
    assert "callNativeLongRequest('get_settings_info'" in settings
    assert "callNativeRequest('get_sync_inputs'" in settings
    assert "nativeBackendUnavailableMessage()" in reader
    assert "nativeBackendUnavailableMessage()" in settings


def test_normal_cli_routes_to_the_native_typed_bridge_not_a_static_server():
    run_console = MAIN_SOURCE[
        MAIN_SOURCE.index("def run_continuous_console") : MAIN_SOURCE.index(
            "def main", MAIN_SOURCE.index("def run_continuous_console")
        )
    ]
    launcher = LAUNCHER_SOURCE[
        LAUNCHER_SOURCE.index("def launch_control_console") :
    ]

    assert "launch_control_console(vault_path)" in run_console
    assert "FuentePyWebViewApi(backend)" in launcher
    assert "js_api=api" in launcher
    assert "http.server" not in MAIN_SOURCE
    assert "http.server" not in LAUNCHER_SOURCE


def test_first_run_stays_unconfigured_until_settings_selects_a_vault():
    assert "load_startup_vault()" in MAIN_SOURCE
    assert "Fuente_Vault" in MAIN_SOURCE  # CLI-only fallback for flush/headless.
    assert "FuenteSetupBackend" in LAUNCHER_SOURCE
    assert "Fuente iniciando servicios" in LAUNCHER_SOURCE
    assert "mode=\"indeterminate\"" in LAUNCHER_SOURCE
    assert "No hay un Vault conectado. Configúralo desde Ajustes." in SOURCE
    assert "restart_with_vault" in SOURCE


def test_packaged_macos_resolves_html_from_resources():
    assert 'bundle_root.parent / "Resources" / "consola_preview.html"' in LAUNCHER_SOURCE
    bootstrap = (ROOT / "fuente" / "bootstrap.py").read_text(encoding="utf-8")
    assert 'bundle_root.parent / "Resources" / "consola_preview.html"' in bootstrap
    assert "url=str(html_file)" in bootstrap
    assert ".as_uri()" not in bootstrap
    assert ".as_uri()" not in LAUNCHER_SOURCE


def test_onboarding_actions_surface_native_bridge_errors():
    create = _function_source("createDemoVault", "dismissOnboarding")
    dismiss = _function_source("dismissOnboarding", "openOnboardingFromHelp")
    assert "callNativeRequest('install_demo_vault'" in create
    assert "callNativeRequest('dismiss_onboarding'" in dismiss
    assert create.count(".catch(function(err)") == 1
    assert dismiss.count(".catch(function(err)") == 1


def test_approval_inbox_loads_when_opened():
    opener = _function_source("openApprovalInbox", "setTextMessage")

    assert "openModal('modal-approval');" in opener
    assert "loadApprovalInbox();" in opener


def test_settings_restart_validates_selected_vault_before_relaunch():
    assert "validate_vault_path" in SETUP_SOURCE
    assert "def restart_with_vault" in BRIDGE_SOURCE
    assert "os.execv(sys.executable" in BRIDGE_SOURCE


def test_setup_api_exposes_empty_sync_state_before_runtime_connection():
    setup_api = (ROOT / "fuente" / "ui" / "setup_api.py").read_text(encoding="utf-8")
    assert "def get_sync_inputs" in setup_api
    assert "return self.backend.get_sync_inputs()" in setup_api
    assert "def get_sync_sources" in setup_api
    assert "return self.backend.get_sync_sources()" in setup_api


def test_guided_vault_confirms_the_exact_creation_path():
    guided = _function_source("createGuidedVault", "renderCapabilities")
    assert "typeof targetPath !== 'string'" in guided
    assert "callNativeLongRequest('select_vault_target'" in guided
    assert "target_path: targetPath" in guided
    assert "consent: true" in guided
    assert "pathInput.value = result.vault_path || ''" in guided
    assert "Carpeta elegida: ' + targetPath" in guided
    assert "No se recibió respuesta al crear el Vault." in guided
    assert "Selección cancelada o sin carpeta." in guided
    assert "El Vault Fuente se creará exactamente en:" in guided
    assert "Fuente configurará los recursos ocultos y consultará la CLI de Obsidian." in guided


def test_note_content_rejection_and_malformed_payload_render_visible_error():
    loader = _function_source("loadNoteContent", "loadCategoryData")

    assert "renderReaderContentError(" in loader
    assert ".catch(function(err)" in loader
    assert "Array.isArray(res.document)" in loader


def test_settings_and_mounted_inputs_load_independently_with_visible_errors():
    loader = _function_source("loadSettingsData", "showButtonFeedback")

    assert "Promise.all" not in loader
    assert "callNativeLongRequest('get_settings_info'" in loader
    assert "callNativeRequest('get_sync_inputs'" in loader
    assert "renderSettingsLoadError(" in loader
    assert "renderSyncInputsLoadError(" in loader
    assert loader.count(".catch(function(err)") >= 2
    assert 'id="settings-load-status"' in SOURCE
    assert 'id="sync-status-summary"' in SOURCE


def test_save_settings_reports_failure_and_closes_only_after_success():
    saver = _function_source("saveSettings", "resetDefaultSettings")

    assert ".catch(function(err)" in saver
    assert "renderSettingsSaveError(" in saver
    assert "closeModal('modal-settings')" in saver
    assert saver.index("closeModal('modal-settings')") > saver.index(
        "Ajustes guardados"
    )


def test_save_settings_rejects_empty_success_response():
    validator = _function_source("isValidSettingsSaveResponse", "saveSettings")

    assert "!!res" in validator
    assert "!res.error" in validator
    assert "res.log.trim().length > 0" in validator
    assert "res.status === 'saved'" in validator


def test_save_settings_accepts_existing_success_response_shapes():
    validator = _function_source("isValidSettingsSaveResponse", "saveSettings")

    assert "typeof res.log === 'string'" in validator
    assert "res.status === 'saved'" in validator
    assert "isValidSettingsSaveResponse(res)" in _function_source(
        "saveSettings", "resetDefaultSettings"
    )
