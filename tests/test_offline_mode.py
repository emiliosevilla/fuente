import re
from pathlib import Path

from fuente.config import (
    AppConfig,
    EXTERNAL_ENABLED_MODE,
    LOCAL_ONLY_MODE,
    VaultConfig,
    describe_offline_mode,
)
from fuente.control_console import FuenteConsoleBackend

CONSOLE_HTML = Path(__file__).resolve().parent.parent / "consola_preview.html"

FORBIDDEN_RUNTIME_CDN_PATTERNS = (
    r"fonts\.googleapis\.com",
    r"fonts\.gstatic\.com",
    r"cdn\.jsdelivr\.net",
    r"unpkg\.com",
    r"cdnjs\.cloudflare\.com",
    r"bootstrapcdn\.com",
)

ALLOWED_LOOPBACK_URL_RE = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?",
    re.IGNORECASE,
)


def _external_http_urls(source: str) -> list[str]:
    urls = re.findall(r"https?://[^\s\"'<>]+", source, flags=re.IGNORECASE)
    disallowed = []
    for url in urls:
        if FORBIDDEN_RUNTIME_CDN_PATTERNS and any(
            re.search(pattern, url, flags=re.IGNORECASE)
            for pattern in FORBIDDEN_RUNTIME_CDN_PATTERNS
        ):
            disallowed.append(url)
            continue
        if ALLOWED_LOOPBACK_URL_RE.fullmatch(url.rstrip(".,);")):
            continue
        disallowed.append(url)
    return disallowed


def test_runtime_html_has_no_external_cdn_urls():
    source = CONSOLE_HTML.read_text(encoding="utf-8")
    for pattern in FORBIDDEN_RUNTIME_CDN_PATTERNS:
        assert not re.search(pattern, source, flags=re.IGNORECASE), (
            f"Forbidden CDN reference found: {pattern}"
        )
    assert "font-src 'self'" in source
    css = (CONSOLE_HTML.parent / "fuente/ui/static/console.css").read_text(encoding="utf-8")
    assert "font-family: var(--font-mono)" in css


def test_runtime_html_external_http_urls_are_loopback_only():
    source = CONSOLE_HTML.read_text(encoding="utf-8")
    assert _external_http_urls(source) == []


def test_describe_offline_mode_defaults_to_local_only():
    config = AppConfig(vault=VaultConfig(vault_path=Path("/tmp/vault")))
    status = describe_offline_mode(config)
    assert status["mode"] == LOCAL_ONLY_MODE
    assert status["is_local_only"] is True
    assert status["ollama_is_loopback"] is True
    assert "100%" not in status["chat_welcome"]
    assert "100%" not in status["chat_footer"]


def test_describe_offline_mode_external_when_non_loopback_url():
    config = AppConfig(
        vault=VaultConfig(vault_path=Path("/tmp/vault")),
        ollama_url="http://192.168.1.50:11434",
        allow_non_loopback_ollama=True,
    )
    status = describe_offline_mode(config)
    assert status["mode"] == EXTERNAL_ENABLED_MODE
    assert status["is_local_only"] is False
    assert "100%" not in status["chat_welcome"].lower()
    assert "100%" not in status["chat_footer"].lower()
    assert "externo" in status["chat_footer"].lower() or "dispositivo" in status["chat_footer"].lower()


def test_console_initial_state_exposes_offline_mode(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    state = backend.get_initial_state_dict()
    assert "offline_mode" in state
    assert state["offline_mode"]["is_local_only"] is True


def test_settings_info_exposes_offline_mode(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    info = backend.get_settings_info()
    assert info["offline_mode"]["mode"] == LOCAL_ONLY_MODE


def test_save_settings_response_includes_offline_mode(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    result = backend.save_settings(
        {
            "ollama_url": "http://192.168.1.10:11434",
            "allow_non_loopback_ollama": True,
        }
    )
    assert "offline_mode" in result
    assert result["offline_mode"]["mode"] == EXTERNAL_ENABLED_MODE
    assert "warning" in result
