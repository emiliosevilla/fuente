"""Shared fixtures and assertions for the Task 8.1 security matrix."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from fuente.domain.paths import AuthorizedPathResolver

MALICIOUS_APPLESCRIPT_INPUT = (
    'Title " \\ \n") & do shell script "touch /tmp/pwned" & ("'
)

def assert_html_fails_closed(html: str) -> None:
    """Generated HTML must not contain executable user-controlled attributes."""
    payload = html or ""
    # Only unescaped markup is executable; escaped entities remain inert text.
    assert re.search(r"<(script|iframe|object|embed)\b", payload, re.IGNORECASE) is None
    assert re.search(r"<[^>]*\son\w+\s*=", payload, re.IGNORECASE) is None
    assert (
        re.search(
            r"""<[^>]*(?:href|src)\s*=\s*['"]?\s*javascript:""",
            payload,
            re.IGNORECASE,
        )
        is None
    )
    assert (
        re.search(
            r"""<[^>]*(?:href|src)\s*=\s*['"]?\s*data:text/html""",
            payload,
            re.IGNORECASE,
        )
        is None
    )


@pytest.fixture
def path_resolver(temp_vault_path):
    roots = {
        "output": temp_vault_path / "4_salida",
        "input": temp_vault_path / "1_entrada",
        "dirty": temp_vault_path / "2_sucio",
        "clean": temp_vault_path / "3_limpio",
        "quarantine": temp_vault_path / ".fuente" / "quarantine",
    }
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return AuthorizedPathResolver(vault_root=temp_vault_path, **roots)


@pytest.fixture
def external_note_path(temp_vault_path) -> Path:
    external = temp_vault_path.parent / "outside.md"
    external.write_text("secret", encoding="utf-8")
    return external
