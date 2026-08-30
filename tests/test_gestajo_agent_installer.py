import sys
import types

from fuente import main as fuente_main
from fuente.agent import tls
from fuente.bootstrap import is_gestajo_agent_install_request


def test_only_the_fixed_gestajo_agent_url_can_open_the_installer():
    assert is_gestajo_agent_install_request(["fuente://gestajo-agent/install"])
    assert not is_gestajo_agent_install_request(["fuente://gestajo-agent/install?force=true"])
    assert not is_gestajo_agent_install_request(["fuente://other/install"])


def test_direct_agent_install_registers_the_connector(monkeypatch):
    events: list[str] = []

    class Root:
        def withdraw(self):
            events.append("withdraw")

        def destroy(self):
            events.append("destroy")

    tkinter = types.ModuleType("tkinter")
    messagebox = types.ModuleType("tkinter.messagebox")
    tkinter.Tk = Root
    tkinter.messagebox = messagebox
    messagebox.askyesno = lambda *_args, **_kwargs: True
    messagebox.showinfo = lambda *_args, **_kwargs: events.append("info")
    messagebox.showwarning = lambda *_args, **_kwargs: events.append("warning")
    monkeypatch.setitem(sys.modules, "tkinter", tkinter)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", messagebox)
    monkeypatch.setattr(tls, "prepare_agent_tls", lambda _confirm: (True, "TLS listo"))
    monkeypatch.setattr(tls, "register_agent_protocol", lambda: (True, "conector listo"))

    assert fuente_main.run_gestajo_agent_install() is True
    assert events == ["withdraw", "info", "destroy"]
