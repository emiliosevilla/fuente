from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import pytest

import fuente.application.onboarding as onboarding_module
from fuente.application.onboarding import OnboardingService
from fuente.domain.frontmatter import parse_frontmatter
from fuente.domain.paths import AuthorizedPathResolver


def _service(vault: Path) -> OnboardingService:
    return OnboardingService(vault)


def _manifest() -> dict:
    return json.loads(
        resources.files("fuente.resources.demo_vault")
        .joinpath("manifest.json")
        .read_text(encoding="utf-8")
    )


def test_demo_vault_declares_six_root_layout():
    manifest = _manifest()
    assert manifest["layout_version"] == 4
    assert manifest["roots"] == [
        "1_volcado/personal", "1_volcado/común", "2_copiado", "3_capturado", "4_procesado", "5_compartido"
    ]
    assert manifest["legacy_destination_root"] == "4_salida"


def test_demo_vault_is_idempotent_and_never_overwrites(tmp_path: Path):
    vault = tmp_path / "Vault"
    vault.mkdir()
    service = _service(vault)

    first = service.install_demo_vault()
    assert first.status == "demo_installed"
    assert len(first.created_paths) == 3

    protected = vault / first.created_paths[0]
    protected.write_text("edición humana", encoding="utf-8")
    second = service.install_demo_vault()

    assert second.status == "demo_installed"
    assert second.created_paths == ()
    assert protected.read_text(encoding="utf-8") == "edición humana"
    assert json.loads((vault / ".fuente" / "onboarding.json").read_text())[
        "status"
    ] == "demo_installed"


def test_collision_blocks_before_any_demo_or_marker_write(tmp_path: Path):
    vault = tmp_path / "Vault"
    collision = vault / "4_procesado" / "Demo" / "Arquitectura_Local.md"
    collision.parent.mkdir(parents=True)
    collision.write_text("contenido humano", encoding="utf-8")
    service = _service(vault)

    result = service.install_demo_vault()

    assert result.status == "blocked"
    assert "4_procesado/Demo/Arquitectura_Local.md" in result.collisions
    assert not (vault / "4_procesado" / "Demo" / "Introduccion.md").exists()
    assert not (vault / "4_procesado" / "Demo" / "Flujo_Revision.md").exists()
    assert not (vault / ".fuente" / "onboarding.json").exists()
    assert collision.read_text(encoding="utf-8") == "contenido humano"


@pytest.mark.parametrize(
    "initial_marker",
    [
        None,
        b'{"schema_version": 1, "status": "dismissed", "demo_version": null, "updated_at": "before"}',
    ],
    ids=["marker-absent", "marker-intact"],
)
def test_install_rolls_back_notes_when_second_atomic_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, initial_marker: bytes | None
):
    vault = tmp_path / "Vault"
    marker = vault / ".fuente" / "onboarding.json"
    if initial_marker is not None:
        marker.parent.mkdir(parents=True)
        marker.write_bytes(initial_marker)
    service = _service(vault)

    original_write = onboarding_module.atomic_write_text
    calls = 0

    def fail_after_first_write(path: str | Path, content: str):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated second-note failure")
        return original_write(path, content)

    monkeypatch.setattr(onboarding_module, "atomic_write_text", fail_after_first_write)

    result = service.install_demo_vault()

    assert result.status == "blocked"
    assert calls == 2
    assert not list((vault / "4_procesado").rglob("*.md"))
    if initial_marker is None:
        assert not marker.exists()
    else:
        assert marker.read_bytes() == initial_marker


def test_preexisting_identical_notes_are_classified_without_rewriting(tmp_path: Path):
    vault = tmp_path / "Vault"
    service = _service(vault)
    manifest = _manifest()
    bundle = resources.files("fuente.resources.demo_vault")
    for entry in manifest["notes"]:
        destination = vault / entry["destination"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(bundle.joinpath(entry["source_resource"]).read_bytes())

    result = service.install_demo_vault()

    assert result.status == "demo_installed"
    assert result.created_paths == ()
    assert set(result.already_identical_paths) == {
        entry["destination"] for entry in manifest["notes"]
    }


def test_dismissed_onboarding_does_not_auto_prompt(tmp_path: Path):
    vault = tmp_path / "Vault"
    vault.mkdir()
    service = _service(vault)

    status = service.dismiss()

    assert status.status == "dismissed"
    assert service.status().show_first_run_panel is False
    assert not (vault / "4_procesado" / "Demo").exists()
    marker = json.loads((vault / ".fuente" / "onboarding.json").read_text())
    assert marker["status"] == "dismissed"


def test_demo_manifest_notes_have_schema_one_and_resolvable_links(tmp_path: Path):
    vault = tmp_path / "Vault"
    service = _service(vault)
    result = service.install_demo_vault()
    assert result.status == "demo_installed"

    resolver = AuthorizedPathResolver(
        vault_root=vault,
        output=vault / "4_procesado",
        input=vault / "1_volcado",
        dirty=vault / "2_copiado",
        clean=vault / "3_capturado",
        quarantine=vault / ".fuente" / "quarantine",
    )
    manifest = _manifest()
    pending = 0
    for entry in manifest["notes"]:
        destination = entry["destination"]
        path = resolver.resolve_note(destination)
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        assert metadata["schema_version"] == 1
        assert metadata["status"] == entry["expected_initial_review_status"]
        if metadata["status"] == "pending_review":
            pending += 1
        for target in entry["expected_wikilinks"]:
            assert resolver.resolve_wikilink_target(target).is_file()
            assert f"[[{target}]]" in body
    assert pending == 1
