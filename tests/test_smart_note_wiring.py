"""The ETL pipeline must stop at the approved capture."""

from dataclasses import replace

from fuente.config import get_default_config
from fuente.watcher.watcher import ETLPipeline


def test_pipeline_does_not_wire_automatic_note_generation(temp_vault_path):
    pipeline = ETLPipeline(get_default_config(temp_vault_path))

    assert pipeline.ingestion.smart_note_generator is None


def test_pipeline_rebinds_ram_governor_after_settings_change(temp_vault_path):
    pipeline = ETLPipeline(get_default_config(temp_vault_path))

    pipeline.set_config(replace(
        pipeline.config,
        anythingllm_url="http://127.0.0.1:13001",
        anythingllm_workspace_slug="gestajo",
        ram_safety_margin_pct=0.5,
    ))

    assert pipeline.ingestion.ram_governor is pipeline.ram_governor
