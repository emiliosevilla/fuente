"""The real ETL pipeline must use the existing smart-note generator."""

from fuente.application.smart_notes import OllamaConversationClient, SmartNoteGenerator
from fuente.config import get_default_config
from fuente.watcher.watcher import ETLPipeline


def test_pipeline_wires_smart_note_generation(temp_vault_path):
    pipeline = ETLPipeline(get_default_config(temp_vault_path))

    assert isinstance(pipeline.ingestion.smart_note_generator, SmartNoteGenerator)
    assert isinstance(pipeline.ingestion.smart_note_generator.chat_client, OllamaConversationClient)
