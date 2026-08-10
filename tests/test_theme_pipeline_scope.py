"""Theme-aware Vault scope for pipeline roots (Task 3.1).

Proves that processing and connected-folder sync stay inside the active Theme
and never silently target the General vault-root tree.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from funes.application.lifecycle import ApplicationLifecycle
from funes.config import get_default_config
from funes.control_console import FunesConsoleBackend
from funes.core.folder_sync import FolderSyncManager
from funes.core.vault import VaultManager, document_id_for_relative_path
from funes.domain.frontmatter import serialize_frontmatter
from funes.domain.runtime_policy import ExecutionProfile, RuntimePolicy
from funes.graph_engine.optimized_loop import OptimizadoGraphLoop
from funes.watcher.watcher import ETLPipeline, FolderMonitor


THEME = "Derecho_Civil"
SOURCE_NAME = "tema_scope_doc.txt"
SOURCE_BODY = "# Nota de Tema\n\nContenido exclusivo del Tema activo."


def _mock_generate(clean_md_content, model_name, file_name):
    stem = Path(file_name).stem
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": stem,
            "date": "",
            "author": "Funes",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "sources": [file_name],
            "history": [],
        }
    ) + f"# {stem}\n\n{clean_md_content}"


def _general_roots(vault_path: Path) -> dict[str, Path]:
    return {
        "input": vault_path / "1_entrada",
        "dirty": vault_path / "2_sucio",
        "clean": vault_path / "3_limpio",
        "output": vault_path / "4_salida",
    }


def _assert_under_theme(path: Path, theme_dir: Path) -> None:
    assert path.resolve().is_relative_to(theme_dir.resolve()), (
        f"{path} is not inside active theme {theme_dir}"
    )


@pytest.fixture
def themed_pipeline(temp_vault_path):
    from tests.conftest import patch_abundant_ram

    config = get_default_config(temp_vault_path)
    # Ensure General roots exist so a silent write would be detectable.
    for root in _general_roots(temp_vault_path).values():
        root.mkdir(parents=True, exist_ok=True)

    pipeline = ETLPipeline(config)
    pipeline.set_runtime_policy(
        RuntimePolicy(
            profile=ExecutionProfile.AUTO,
            retrieval_mode="hybrid",
            vector_index_enabled=True,
            audio_mode="auto",
            whisper_model_path=None,
            allow_model_download=False,
            selected_model="qwen2.5:1.5b",
            llm_available=True,
            reason="test fixture provides an installed model explicitly",
        )
    )
    patch_abundant_ram(pipeline.ram_governor)
    pipeline.vault.create_theme(THEME)
    # create_theme already activates the Theme; rebind linker caches.
    pipeline.set_active_theme(THEME)
    yield pipeline
    pipeline.close()


@patch(
    "funes.watcher.watcher.AtomicNoteGenerator.generate_atomic_note",
    side_effect=_mock_generate,
)
def test_processing_writes_only_inside_active_theme(mock_gen, themed_pipeline):
    pipeline = themed_pipeline
    theme_dir = pipeline.vault.current_theme_dir
    general = _general_roots(pipeline.config.vault.vault_path)

    source = pipeline.vault.input_dir / SOURCE_NAME
    source.write_text(SOURCE_BODY, encoding="utf-8")
    assert source.resolve().is_relative_to(theme_dir.resolve())

    assert pipeline.process_file(source) is True

    dirty = list(pipeline.vault.dirty_dir.glob(f"{Path(SOURCE_NAME).stem}*"))
    clean = list(pipeline.vault.clean_dir.glob(f"{Path(SOURCE_NAME).stem}*.md"))
    notes = list(pipeline.vault.output_dir.rglob(f"{Path(SOURCE_NAME).stem}*.md"))

    assert len(dirty) == 1
    assert len(clean) == 1
    assert len(notes) == 1
    for path in (*dirty, *clean, *notes):
        _assert_under_theme(path, theme_dir)

    # General root pipeline dirs must not receive any of this Theme's artifacts.
    assert list(general["dirty"].glob(f"{Path(SOURCE_NAME).stem}*")) == []
    assert list(general["clean"].glob(f"{Path(SOURCE_NAME).stem}*.md")) == []
    assert list(general["output"].rglob(f"{Path(SOURCE_NAME).stem}*.md")) == []
    assert list(general["input"].glob(SOURCE_NAME)) == []

    # FolderMonitor must poll the Theme input, not config.vault.input_dir.
    monitor = FolderMonitor(pipeline, poll_interval_sec=3600.0)
    assert monitor.pipeline.vault.input_dir == theme_dir / "1_entrada"
    assert monitor.pipeline.vault.input_dir != general["input"]


def test_connected_folder_sync_stays_in_active_theme(temp_vault_path, tmp_path):
    config = get_default_config(temp_vault_path)
    vault = VaultManager(config.vault)
    for root in _general_roots(temp_vault_path).values():
        root.mkdir(parents=True, exist_ok=True)

    vault.create_theme(THEME)
    assert vault.active_theme == THEME

    external = tmp_path / "connected_source"
    external.mkdir()
    sample = external / "from_sharepoint.txt"
    sample.write_text("documento externo del Tema", encoding="utf-8")

    sync = FolderSyncManager(temp_vault_path)
    assert sync.save_connected_folders([external])

    copied = sync.sync_to_input(vault.input_dir, vault.dirty_dir)
    assert copied == 1

    theme_dest = vault.input_dir / sample.name
    general_dest = temp_vault_path / "1_entrada" / sample.name

    assert theme_dest.exists()
    assert theme_dest.read_text(encoding="utf-8") == "documento externo del Tema"
    assert not general_dest.exists(), (
        "connected-folder sync silently wrote into the General root"
    )
    assert sample.exists(), "source file in the connected folder must remain intact"


def test_enumerate_documents_excludes_system_hidden_moc_and_quarantine(temp_vault_path):
    config = get_default_config(temp_vault_path)
    vault = VaultManager(config.vault)
    vault.create_theme(THEME)

    issue = vault.create_issue_in_theme("Contratos")
    note = issue / "Obligaciones.md"
    note.write_text("# Obligaciones\n", encoding="utf-8")

    default_issue_note = vault.output_dir / "_Sin_Cuestion" / "Nota_Default.md"
    default_issue_note.parent.mkdir(parents=True, exist_ok=True)
    default_issue_note.write_text("# Default\n", encoding="utf-8")

    moc = vault.output_dir / "_Indice_MOC.md"
    moc.write_text("# MOC\n", encoding="utf-8")

    hidden = vault.output_dir / ".hidden_note.md"
    hidden.write_text("# hidden\n", encoding="utf-8")

    system_noise = config.vault.system_dir / "noise.md"
    system_noise.parent.mkdir(parents=True, exist_ok=True)
    system_noise.write_text("# system\n", encoding="utf-8")

    quarantined = vault.quarantine_dir / "lost.md"
    quarantined.write_text("# lost\n", encoding="utf-8")

    listed = vault.enumerate_documents("output")
    relative_paths = {rel for _, rel in listed}

    assert any(rel.endswith("Contratos/Obligaciones.md") for rel in relative_paths)
    assert any(rel.endswith("_Sin_Cuestion/Nota_Default.md") for rel in relative_paths)
    assert all(not rel.endswith("_Indice_MOC.md") for rel in relative_paths)
    assert all(".hidden_note.md" not in rel for rel in relative_paths)
    assert all(".funes" not in rel for rel in relative_paths)
    assert all("quarantine" not in rel for rel in relative_paths)

    for document_id, relative in listed:
        assert document_id == document_id_for_relative_path(relative)
        assert document_id != relative


def test_lifecycle_set_active_theme_retargets_monitor_and_graph_loop(temp_vault_path):
    """After theme switch, FolderMonitor process path and graph loop use Theme roots."""
    config = get_default_config(temp_vault_path)
    for root in _general_roots(temp_vault_path).values():
        root.mkdir(parents=True, exist_ok=True)

    lifecycle = ApplicationLifecycle(
        config,
        mode="continuous",
        # Real monitor/graph with huge intervals so start/stop stay cheap.
        monitor_factory=lambda pipeline: FolderMonitor(pipeline, poll_interval_sec=3600.0),
        graph_loop_factory=lambda output_dir: OptimizadoGraphLoop(
            output_dir, interval_sec=3600
        ),
    )
    try:
        lifecycle.start()
        assert lifecycle.pipeline is not None
        assert lifecycle.monitor is not None
        assert lifecycle.graph_loop is not None

        general_input = lifecycle.pipeline.vault.input_dir
        general_output = lifecycle.pipeline.vault.output_dir
        assert general_input == temp_vault_path / "1_entrada"
        assert lifecycle.graph_loop.output_dir.resolve() == general_output.resolve()

        lifecycle.pipeline.vault.create_theme(THEME)
        lifecycle.set_active_theme(THEME)

        theme_input = lifecycle.pipeline.vault.input_dir
        theme_output = lifecycle.pipeline.vault.output_dir
        assert theme_input == temp_vault_path / THEME / "1_entrada"
        assert theme_input != general_input
        assert theme_output != general_output

        # FolderMonitor reads pipeline.vault each poll / process_existing path.
        assert lifecycle.monitor.pipeline.vault.input_dir == theme_input
        assert lifecycle.monitor.pipeline.vault.input_dir != (
            temp_vault_path / "1_entrada"
        )

        # Graph loop must not keep refining only the General tree.
        assert lifecycle.graph_loop.output_dir.resolve() == theme_output.resolve()
        assert lifecycle.pipeline.linker.output_dir.resolve() == theme_output.resolve()
    finally:
        lifecycle.stop()


def test_console_set_theme_shares_lifecycle_vault_and_retargets_services(temp_vault_path):
    """Console theme API must drive the lifecycle-owned pipeline, not a private vault."""
    for root in _general_roots(temp_vault_path).values():
        root.mkdir(parents=True, exist_ok=True)

    backend = FunesConsoleBackend(temp_vault_path)
    lifecycle = ApplicationLifecycle(
        backend.config,
        mode="continuous",
        monitor_factory=lambda pipeline: FolderMonitor(pipeline, poll_interval_sec=3600.0),
        graph_loop_factory=lambda output_dir: OptimizadoGraphLoop(
            output_dir, interval_sec=3600
        ),
    )
    try:
        lifecycle.start()
        backend.attach_lifecycle(lifecycle)

        assert backend.vault is lifecycle.pipeline.vault

        # Seed Theme via console create, then switch away and back via set_theme.
        created = backend.handle_action("create_theme", {"theme_name": THEME})
        assert "error" not in created
        assert backend.vault.active_theme == THEME
        assert lifecycle.pipeline.vault.active_theme == THEME
        assert lifecycle.monitor.pipeline.vault.input_dir == (
            temp_vault_path / THEME / "1_entrada"
        )
        assert lifecycle.graph_loop.output_dir.resolve() == (
            temp_vault_path / THEME / "4_salida"
        ).resolve()

        backend.handle_action("set_theme", {"theme_name": "General"})
        assert lifecycle.pipeline.vault.active_theme == "General"
        assert lifecycle.monitor.pipeline.vault.input_dir == temp_vault_path / "1_entrada"
        assert lifecycle.graph_loop.output_dir.resolve() == (
            temp_vault_path / "4_salida"
        ).resolve()

        backend.handle_action("set_theme", {"theme_name": THEME})
        assert lifecycle.monitor.pipeline.vault.input_dir == (
            temp_vault_path / THEME / "1_entrada"
        )
        assert lifecycle.graph_loop.output_dir.resolve() == (
            temp_vault_path / THEME / "4_salida"
        ).resolve()
        assert backend.vault is lifecycle.pipeline.vault
    finally:
        lifecycle.stop()
