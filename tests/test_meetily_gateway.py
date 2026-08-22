from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from fuente.application.meetings import MeetingCaptureRequest
from fuente.config import (
    DEFAULT_MEETILY_BRIDGE_COMMAND,
    AppConfig,
    VaultConfig,
    validate_meetily_bridge_command,
)
from fuente.integrations.meetily import (
    MeetingBridgePermissionError,
    MeetingBridgeProtocolError,
    MeetingBridgeUnavailable,
    MeetilyGatewayClient,
)


class FakeProcess:
    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


def config(tmp_path: Path, command=DEFAULT_MEETILY_BRIDGE_COMMAND) -> AppConfig:
    return AppConfig(
        vault=VaultConfig(vault_path=tmp_path),
        meetily_bridge_command=command,
    )


def request(title="Tema") -> MeetingCaptureRequest:
    return MeetingCaptureRequest(theme_id="general", title=title, requested_by="pytest")


def transport_for(**responses):
    calls = []

    def transport(endpoint, operation, payload, token):
        calls.append((endpoint, operation, payload, token))
        response = responses.get(operation)
        if isinstance(response, Exception):
            raise response
        return response or {"session_id": payload["session_id"], "status": "recording"}

    transport.calls = calls
    return transport


def artifacts_payload(session_id):
    return {
        "session_id": session_id,
        "provider": "meetily",
        "provider_revision": "0281737d87d26352fb0adc78c8c0975f691b23d1",
        "template_id": "standard_meeting",
        "recording_path": f".fuente/reunion/{session_id}/recording.m4a",
        "transcript_markdown": "# Transcript\n\n- agreed\n",
        "notes_markdown": None,
        "recording_sha256": "a" * 64,
    }


def test_bridge_uses_one_time_loopback_token_and_never_legacy_backend(tmp_path):
    processes = []

    def process_factory(argv, **kwargs):
        process = FakeProcess(argv, **kwargs)
        processes.append(process)
        return process

    gateway = MeetilyGatewayClient(
        config(tmp_path, "/opt/meetily-bridge"),
        transport=lambda endpoint, operation, payload, token: {
            "session_id": payload["session_id"],
            "status": "recording",
        },
        process_factory=process_factory,
        port_factory=lambda: 18080,
    )

    session_id = gateway.start(request())

    assert gateway.last_command is not None
    assert gateway.last_command.endpoint.startswith("http://127.0.0.1:")
    assert "/backend/" not in gateway.last_command.executable
    assert gateway.last_command.token != gateway.next_token
    assert "--host" in processes[0].argv
    assert "127.0.0.1" in processes[0].argv
    assert "--preparation-dir" in processes[0].argv
    assert str(tmp_path) not in processes[0].argv
    assert processes[0].argv[0] == "/opt/meetily-bridge"
    assert "--output" not in processes[0].argv
    assert "/tmp/outside" not in processes[0].argv
    assert session_id == gateway.last_command.session_id


def test_bridge_requires_consent_before_launch(tmp_path):
    launched = []
    gateway = MeetilyGatewayClient(
        config(tmp_path),
        process_factory=lambda *args, **kwargs: launched.append(args),
        port_factory=lambda: 18080,
    )

    with pytest.raises(MeetingBridgePermissionError, match="consent"):
        gateway.start(request(), consent=False)

    assert launched == []


@pytest.mark.parametrize(
    "command",
    [
        "meetily-local-bridge",
        ("/tmp/backend/meetily",),
        ("meetily;touch /tmp/out",),
        ("meetily-local-bridge", "--cloud"),
        ("meetily-local-bridge", "--preparation-dir", "/tmp/outside"),
        ("meetily-local-bridge", "--output", "/tmp/outside"),
        ("https://cloud.example/meetily",),
    ],
)
def test_bridge_command_is_allow_listed(command):
    with pytest.raises(ValueError):
        validate_meetily_bridge_command(command)


def test_legacy_single_item_setting_is_normalized_but_arguments_are_not_accepted(
    tmp_path,
):
    config_from_legacy = AppConfig.from_dict(
        {
            "vault_path": str(tmp_path),
            "meetily_bridge_command": ["/opt/meetily-bridge"],
        }
    )
    assert config_from_legacy.meetily_bridge_command == "/opt/meetily-bridge"
    assert config_from_legacy.to_dict()["meetily_bridge_command"] == "/opt/meetily-bridge"

    relative_config = AppConfig.from_dict(
        {
            "vault_path": str(tmp_path),
            "meetily_bridge_command": "meetily-local-bridge",
        }
    )
    assert relative_config.meetily_bridge_command == DEFAULT_MEETILY_BRIDGE_COMMAND

    unsafe_config = AppConfig.from_dict(
        {
            "vault_path": str(tmp_path),
            "meetily_bridge_command": ["meetily-local-bridge", "--output", "/tmp/out"],
        }
    )
    assert unsafe_config.meetily_bridge_command == DEFAULT_MEETILY_BRIDGE_COMMAND


def test_app_config_rejects_arbitrary_bridge_arguments(tmp_path):
    with pytest.raises(ValueError):
        AppConfig(
            vault=VaultConfig(vault_path=tmp_path),
            meetily_bridge_command=("meetily-local-bridge", "--preparation-dir", "/tmp/out"),
        )


def test_legacy_path_setting_does_not_invoke_homonymous_path_binary(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "homonym-invoked"
    homonym = bin_dir / "meetily-local-bridge"
    homonym.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('invoked', encoding='utf-8')\n",
        encoding="utf-8",
    )
    homonym.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    commands = []

    def process_factory(argv, **kwargs):
        commands.append(argv)
        if not Path(argv[0]).is_absolute():
            subprocess.run(argv, cwd=kwargs["cwd"], env=os.environ.copy(), check=False)
        raise FileNotFoundError(argv[0])

    gateway = MeetilyGatewayClient(
        AppConfig.from_dict(
            {
                "vault_path": str(tmp_path),
                "meetily_bridge_command": "meetily-local-bridge",
            }
        ),
        process_factory=process_factory,
        port_factory=lambda: 18080,
    )

    with pytest.raises(MeetingBridgeUnavailable):
        gateway.start(request())

    assert commands[0][0] == DEFAULT_MEETILY_BRIDGE_COMMAND
    assert not marker.exists()


def test_missing_executable_creates_recoverable_session(tmp_path):
    gateway = MeetilyGatewayClient(
        config(tmp_path, "/opt/meetily-bridge"), port_factory=lambda: 18080
    )

    with pytest.raises(MeetingBridgeUnavailable):
        gateway.start(request())

    state_files = list((tmp_path / ".fuente" / "reunion").glob("*/bridge_state.json"))
    assert len(state_files) == 1
    state = json.loads(state_files[0].read_text(encoding="utf-8"))
    assert state["status"] == "recoverable"
    assert state["error_code"] == "executable_missing"


def test_denied_microphone_is_recoverable(tmp_path):
    gateway = MeetilyGatewayClient(
        config(tmp_path),
        process_factory=FakeProcess,
        transport=transport_for(start={"error": "microphone_denied"}),
        port_factory=lambda: 18080,
    )

    with pytest.raises(MeetingBridgePermissionError):
        gateway.start(request())

    state_files = list((tmp_path / ".fuente" / "reunion").glob("*/bridge_state.json"))
    state = json.loads(state_files[0].read_text(encoding="utf-8"))
    assert state["status"] == "recoverable"
    assert state["error_code"] == "microphone_denied"


def test_invalid_stop_manifest_is_recoverable_without_outside_write(tmp_path):
    gateway = MeetilyGatewayClient(
        config(tmp_path),
        process_factory=FakeProcess,
        transport=transport_for(stop={"session_id": "wrong", "recording_path": "/tmp/out"}),
        port_factory=lambda: 18080,
    )
    session_id = gateway.start(request())

    with pytest.raises(MeetingBridgeProtocolError):
        gateway.stop(session_id)

    public_manifest = gateway.artifact_manifest(session_id)
    assert public_manifest["status"] == "recoverable"
    assert "token" not in json.dumps(public_manifest)
    assert "/tmp/out" not in json.dumps(public_manifest)
