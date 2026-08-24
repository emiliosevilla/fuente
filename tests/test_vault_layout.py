import json
from pathlib import Path

import pytest

from fuente.config import VaultConfig
from fuente.core.vault import VaultManager
from fuente.domain.vault_layout import VaultLayout


def test_layout_creates_five_exact_roots(tmp_path):
    layout = VaultLayout(tmp_path / "Tema")

    layout.ensure()

    assert layout.input_personal_dir == tmp_path / "Tema" / "1_volcado" / "personal"
    assert layout.input_common_dir == tmp_path / "Tema" / "1_volcado" / "común"
    assert layout.root("dirty") == tmp_path / "Tema" / "2_copiado"
    assert layout.root("clean") == tmp_path / "Tema" / "3_capturado"
    assert layout.processed_dir == tmp_path / "Tema" / "4_procesado"
    assert layout.shared_dir == tmp_path / "Tema" / "5_compartido"
    assert all(path.is_dir() for path in (
        layout.input_personal_dir,
        layout.input_common_dir,
        layout.root("dirty"),
        layout.root("clean"),
        layout.processed_dir,
        layout.shared_dir,
    ))


def test_layout_properties_and_ensure_are_idempotent(tmp_path):
    layout = VaultLayout(tmp_path / "Tema")

    layout.ensure()
    first = sorted(path.relative_to(tmp_path) for path in (tmp_path / "Tema").rglob("*"))
    layout.ensure()

    assert first == sorted(path.relative_to(tmp_path) for path in (tmp_path / "Tema").rglob("*"))


def test_layout_rejects_unknown_root(tmp_path):
    with pytest.raises(ValueError, match="Unknown Vault root"):
        VaultLayout(tmp_path / "Tema").root("not_a_root")  # type: ignore[arg-type]


def test_new_theme_uses_canonical_vault_roots(tmp_path):
    manager = VaultManager(VaultConfig(vault_path=tmp_path / "Vault"))

    theme_dir = manager.create_theme("Tema")

    layout = VaultLayout(theme_dir)
    assert layout.input_personal_dir.is_dir()
    assert layout.input_common_dir.is_dir()
    assert layout.root("dirty").is_dir()
    assert layout.root("clean").is_dir()
    assert layout.processed_dir.is_dir()
    assert layout.shared_dir.is_dir()
    assert manager.output_dir == theme_dir / "4_procesado"
    assert (manager.output_dir / "_Sin_Cuestion").is_dir()
    assert manager.processed_dir == layout.processed_dir
    assert manager.shared_dir == layout.shared_dir


def test_obsidian_hides_only_canonical_private_roots_and_preserves_rules(tmp_path):
    vault = tmp_path / "Vault"
    obsidian = vault / ".obsidian"
    obsidian.mkdir(parents=True)
    (obsidian / "app.json").write_text(
        json.dumps({"userIgnoreFilters": ["existing-rule"], "legacySetting": True}),
        encoding="utf-8",
    )

    VaultManager(VaultConfig(vault_path=vault))

    settings = json.loads((obsidian / "app.json").read_text(encoding="utf-8"))
    assert settings["userIgnoreFilters"] == [
        "existing-rule",
        "1_volcado",
        "2_copiado",
    ]
    assert settings["legacySetting"] is True
    assert "3_capturado" not in settings["userIgnoreFilters"]


def test_legacy_roots_do_not_create_runtime_themes(tmp_path):
    legacy_theme = tmp_path / "TemaLegacy" / "4_salida"
    legacy_theme.mkdir(parents=True)

    manager = VaultManager(VaultConfig(vault_path=tmp_path))

    assert manager.get_available_themes() == ["General"]
    assert manager.current_theme_dir == tmp_path
