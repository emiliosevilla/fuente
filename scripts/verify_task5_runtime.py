#!/usr/bin/env python3
"""Reproduce Task 5 against Cocoa PyWebView and the real Fuente bridge."""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "consola_preview.html"


def _child(phase: str, vault: Path) -> int:
    import webview

    from fuente.infrastructure.sqlite_store import JobStore
    from fuente.ui.bridge import FuentePyWebViewApi

    original_connect = sqlite3.connect
    connection_count = 0

    def measured_connect(*args, **kwargs):
        nonlocal connection_count
        connection_count += 1
        return original_connect(*args, **kwargs)

    sqlite3.connect = measured_connect
    store = JobStore(vault)
    backend = SimpleNamespace(
        _job_store=store,
        get_notes_service=lambda: SimpleNamespace(job_store=store),
        get_initial_state_dict=lambda: {},
    )
    api = FuentePyWebViewApi(backend)
    result: dict[str, object] = {}
    window = webview.create_window(
        f"Fuente Task 5 {phase}",
        url=str(HTML),
        js_api=api,
        width=900,
        height=650,
        hidden=True,
    )
    assert window is not None
    api.set_window(window)

    def finish(value):
        result.update(value or {})
        result["sqlite_connect_calls"] = connection_count
        window.destroy()

    def loaded():
        if phase == "write":
            script = """
                window.pywebview.api.set_ui_state(
                    'persistent', 'main-window', 'workspace', 'flow'
                ).then(function() {
                    return window.pywebview.api.get_ui_state(
                        'persistent', 'main-window', 'workspace'
                    );
                }).then(function(state) {
                    return {
                        workspace: state.value,
                        local_storage_length: window.localStorage.length,
                        user_agent: navigator.userAgent
                    };
                });
            """
        else:
            script = """
                window.pywebview.api.get_ui_state(
                    'persistent', 'main-window', 'workspace'
                ).then(function(state) {
                    return {
                        workspace: state.value,
                        local_storage_length: window.localStorage.length,
                        user_agent: navigator.userAgent
                    };
                });
            """
        window.evaluate_js(script, callback=finish)

    window.events.loaded += loaded
    timer = threading.Timer(25, lambda: window.destroy())
    timer.start()
    try:
        webview.start(gui="cocoa", debug=False, private_mode=True)
    finally:
        timer.cancel()
        store.close()
        sqlite3.connect = original_connect
    if not result:
        raise RuntimeError(f"PyWebView {phase} probe timed out")
    print(json.dumps(result, sort_keys=True))
    return 0


def _run() -> int:
    with tempfile.TemporaryDirectory(prefix="fuente-task5-runtime-") as directory:
        vault = Path(directory)
        phases = []
        for phase in ("write", "read"):
            process = subprocess.run(
                [sys.executable, __file__, "--child", phase, "--vault", str(vault)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=35,
            )
            if process.returncode != 0:
                raise RuntimeError(process.stderr or process.stdout)
            phases.append(json.loads(process.stdout.strip().splitlines()[-1]))

        contract = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_transition_approval_boundaries.py",
                "tests/test_transition_approvals.py::test_transition_approval_uses_only_job_store_connection",
                "-q",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if contract.returncode != 0:
            raise RuntimeError(contract.stdout + contract.stderr)

        checks = {
            "two_process_restart": len(phases) == 2,
            "workspace_restored": [item.get("workspace") for item in phases]
            == ["flow", "flow"],
            "local_storage_empty": all(
                item.get("local_storage_length") == 0 for item in phases
            ),
            "cocoa_webkit": all(
                "AppleWebKit" in str(item.get("user_agent")) for item in phases
            ),
            "one_connection_per_process": all(
                item.get("sqlite_connect_calls") == 1 for item in phases
            ),
            "four_production_boundaries": "5 passed" in contract.stdout,
            "one_state_database": len(list(vault.rglob("state.db"))) == 1,
        }
        output = {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "phases": phases,
            "transition_contract": contract.stdout.strip(),
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0 if all(checks.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", choices=("write", "read"))
    parser.add_argument("--vault", type=Path)
    args = parser.parse_args()
    if args.child:
        if args.vault is None:
            parser.error("--vault is required with --child")
        return _child(args.child, args.vault.resolve())
    return _run()


if __name__ == "__main__":
    raise SystemExit(main())
