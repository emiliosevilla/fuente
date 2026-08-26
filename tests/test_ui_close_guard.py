from __future__ import annotations

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
    window = _Window([{"ready": False}, {"ready": True}])
    bridge.set_window(window)
    monkeypatch.setattr("fuente.ui.bridge.threading.Timer", _ImmediateTimer)

    assert bridge._handle_window_closing() is False
    assert window.destroy_calls == 0

    assert bridge.complete_pending_close() == {"status": "closing"}
    assert window.destroy_calls == 1


def test_restart_waits_for_pending_ui_state_then_relaunches(monkeypatch, tmp_path):
    target = tmp_path.resolve()
    backend = SimpleNamespace(
        validate_vault=lambda _path: {"vault_path": str(target)}
    )
    bridge = FuentePyWebViewApi(backend)
    window = _Window([{"ready": False}, {"ready": True}])
    bridge.set_window(window)
    exec_calls = []
    monkeypatch.setattr("fuente.ui.bridge.threading.Timer", _ImmediateTimer)
    monkeypatch.setattr(
        "fuente.ui.bridge.os.execv", lambda executable, argv: exec_calls.append((executable, argv))
    )

    result = bridge.restart_with_vault(str(target))

    assert result["error"] == "ui_state_pending"
    assert window.destroy_calls == 0
    assert exec_calls == []

    assert bridge.complete_pending_close()["status"] == "restarting"
    assert window.destroy_calls == 1
    assert exec_calls and exec_calls[0][1][-1] == str(target)


def test_uninitialized_test_window_keeps_normal_close_lifecycle():
    bridge = FuentePyWebViewApi(SimpleNamespace())
    bridge.set_window(SimpleNamespace(destroy=lambda: None))

    assert bridge._handle_window_closing() is True
