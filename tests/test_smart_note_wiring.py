"""The real ETL pipeline must use the existing smart-note generator."""

from dataclasses import replace

from fuente.application.smart_notes import OllamaConversationClient, SmartNoteGenerator
from fuente.config import get_default_config
from fuente.integrations.anythingllm import AnythingLLMConversationClient
from fuente.watcher.watcher import ETLPipeline


def test_pipeline_wires_smart_note_generation(temp_vault_path):
    pipeline = ETLPipeline(get_default_config(temp_vault_path))

    assert isinstance(pipeline.ingestion.smart_note_generator, SmartNoteGenerator)
    assert isinstance(pipeline.ingestion.smart_note_generator.chat_client, OllamaConversationClient)


def test_pipeline_rebinds_smart_note_processing_after_settings_change(temp_vault_path):
    pipeline = ETLPipeline(get_default_config(temp_vault_path))

    pipeline.set_config(replace(
        pipeline.config,
        anythingllm_url="http://127.0.0.1:13001",
        anythingllm_workspace_slug="gestajo",
        ram_safety_margin_pct=0.5,
    ))

    smart_notes = pipeline.ingestion.smart_note_generator
    assert smart_notes.ram_governor is pipeline.ram_governor
    assert isinstance(smart_notes.chat_client, AnythingLLMConversationClient)
    assert smart_notes.chat_client.workspace_slug == "gestajo"
