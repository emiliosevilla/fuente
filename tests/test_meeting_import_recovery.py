from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from fuente.application.meetings import (
    MeetingCaptureApplicationService,
    MeetingCaptureRequest,
)
from fuente.config import AppConfig, VaultConfig
from fuente.integrations.meetily import (
    MeetingBridgeError,
    MeetingBridgeProtocolError,
    MeetilyGatewayClient,
)

from tests.test_meetily_gateway import FakeProcess, artifacts_payload, config, transport_for


def test_bridge_loss_reconstructs_recoverable_session(tmp_path: Path):
    transport = transport_for(start=ConnectionError("bridge stopped"))
    gateway = MeetilyGatewayClient(
        config(tmp_path), process_factory=FakeProcess, transport=transport,
        port_factory=lambda: 18080,
    )

    with pytest.raises(MeetingBridgeError):
        gateway.start(MeetingCaptureRequest("general", "Tema", "pytest"))

    session_id = next((tmp_path / ".fuente/reunion").iterdir()).name
    state = json.loads(
        (tmp_path / f".fuente/reunion/{session_id}/bridge_state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["status"] == "recoverable"
    assert state["request"]["title"] == "Tema"


def test_invalid_recovery_manifest_is_rewritten_as_recoverable(tmp_path: Path):
    session_id = "meeting-invalid"
    state_path = tmp_path / f".fuente/reunion/{session_id}/bridge_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("not-json", encoding="utf-8")
    gateway = MeetilyGatewayClient(
        config(tmp_path), process_factory=FakeProcess, port_factory=lambda: 18080
    )

    with pytest.raises(MeetingBridgeProtocolError):
        gateway.recover(session_id)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "recoverable"
    assert state["error_code"] == "manifest_invalid"


def test_application_import_projection_exposes_no_filesystem_paths(tmp_path: Path):
    transport = transport_for()
    gateway = MeetilyGatewayClient(
        config(tmp_path), process_factory=FakeProcess, transport=transport,
        port_factory=lambda: 18080,
    )
    service = MeetingCaptureApplicationService(
        AppConfig(vault=VaultConfig(vault_path=tmp_path)), gateway=gateway
    )

    session_id = service.start(
        MeetingCaptureRequest("general", "Tema", "pytest"), consent=True
    )
    recording = tmp_path / f".fuente/reunion/{session_id}/recording.m4a"
    recording.write_bytes(b"fixture recording")
    artifact_payload = artifacts_payload(session_id)
    artifact_payload["recording_sha256"] = hashlib.sha256(
        recording.read_bytes()
    ).hexdigest()
    gateway._transport = lambda endpoint, operation, request_payload, token: {
        "artifacts": artifact_payload
    }
    result = service.stop(session_id)

    assert result["status"] == "imported"
    assert "relative_path" not in json.dumps(result)
    assert str(tmp_path) not in json.dumps(result)
    service.close()
