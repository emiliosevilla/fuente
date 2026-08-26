from __future__ import annotations

import threading
from types import SimpleNamespace

from fuente.ui.bridge import FuentePyWebViewApi


class _Window:
    def __init__(self, responses):
        self.responses = list(responses)
        self.destroy_calls = 0

    def evaluate_js(self, _script):
        return self.responses.pop(0)

    def destroy(self):
        self.destroy_calls += 1


class _ImmediateTimer:
    def __init__(self, _delay, action):
        self.action = action

    def start(self):
        self.action()


def test_native_close_is_cancelled_until_pending_ui_state_drains(monkeypatch):
    bridge = FuentePyWebViewApi(SimpleNamespace())
    window = _Window([])
    bridge.set_window(window)
    monkeypatch.setattr("fuente.ui.bridge.threading.Timer", _ImmediateTimer)
    bridge.ui_state_pending_changed(1)

    assert bridge._handle_window_closing() is False
    assert window.destroy_calls == 0

    bridge.ui_state_pending_changed(0)
    assert bridge.complete_pending_close() == {"status": "closing"}
    assert window.destroy_calls == 1


def test_restart_waits_for_pending_ui_state_then_relaunches(monkeypatch, tmp_path):
    target = tmp_path.resolve()
    backend = SimpleNamespace(
        validate_vault=lambda _path: {"vault_path": str(target)}
    )
    bridge = FuentePyWebViewApi(backend)
    window = _Window([])
    bridge.set_window(window)
    exec_calls = []
    monkeypatch.setattr("fuente.ui.bridge.threading.Timer", _ImmediateTimer)
    monkeypatch.setattr(
        "fuente.ui.bridge.os.execv", lambda executable, argv: exec_calls.append((executable, argv))
    )
    bridge.ui_state_pending_changed(1)

    result = bridge.restart_with_vault(str(target))

    assert result["error"] == "ui_state_pending"
    assert window.destroy_calls == 0
    assert exec_calls == []

    bridge.ui_state_pending_changed(0)
    assert bridge.complete_pending_close()["status"] == "restarting"
    assert window.destroy_calls == 1
    assert exec_calls and exec_calls[0][1][-1] == str(target)


def test_uninitialized_test_window_keeps_normal_close_lifecycle():
    bridge = FuentePyWebViewApi(SimpleNamespace())
    bridge.set_window(SimpleNamespace(destroy=lambda: None))

    assert bridge._handle_window_closing() is True


def test_native_close_is_cancelled_while_sqlite_write_is_inflight(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_set(*_args, **_kwargs):
        started.set()
        assert release.wait(2)

    monkeypatch.setattr("fuente.ui.bridge.UIStateStore.set", blocking_set)
    bridge = FuentePyWebViewApi(SimpleNamespace(_job_store=SimpleNamespace()))
    bridge.set_window(SimpleNamespace())
    writer = threading.Thread(
        target=bridge.set_ui_state,
        args=("persistent", "reader", "filters", {"search": "pendiente"}),
    )
    writer.start()
    assert started.wait(1)

    assert bridge._handle_window_closing() is False

    release.set()
    writer.join(2)
    assert not writer.is_alive()


def test_native_close_blocks_write_start_after_its_empty_check(monkeypatch):
    writes = []
    monkeypatch.setattr(
        "fuente.ui.bridge.UIStateStore.set",
        lambda *_args: writes.append("started"),
    )
    bridge = FuentePyWebViewApi(SimpleNamespace(_job_store=SimpleNamespace()))
    bridge.set_window(SimpleNamespace())

    assert bridge._handle_window_closing() is True

    result = bridge.set_ui_state(
        "persistent", "reader", "filters", {"search": "too-late"}
    )

    assert result["error"] == "ui_state_closing"
    assert writes == []


def test_native_close_does_not_replace_pending_restart(monkeypatch, tmp_path):
    target = tmp_path.resolve()
    bridge = FuentePyWebViewApi(
        SimpleNamespace(validate_vault=lambda _path: {"vault_path": str(target)})
    )
    window = _Window([])
    bridge.set_window(window)
    exec_calls = []
    monkeypatch.setattr("fuente.ui.bridge.threading.Timer", _ImmediateTimer)
    monkeypatch.setattr(
        "fuente.ui.bridge.os.execv",
        lambda executable, argv: exec_calls.append((executable, argv)),
    )
    bridge.ui_state_pending_changed(1)

    assert bridge.restart_with_vault(str(target))["error"] == "ui_state_pending"
    assert bridge._handle_window_closing() is False

    bridge.ui_state_pending_changed(0)
    result = bridge.complete_pending_close()

    assert result["status"] == "restarting"
    assert len(exec_calls) == 1
    assert exec_calls[0][1][-1] == str(target)
