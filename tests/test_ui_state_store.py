from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from fuente.infrastructure.sqlite_store import JobStore, UIStateStore
from fuente.ui.bridge import FuentePyWebViewApi


def test_persistent_ui_state_survives_store_restart(tmp_path) -> None:
    store = JobStore(tmp_path)
    state = UIStateStore(store)
    state.set("persistent", "main-window", "workspace", "flow")
    store.close()

    reopened = JobStore(tmp_path)
    try:
        assert UIStateStore(reopened).get("persistent", "main-window", "workspace") == "flow"
        assert list(tmp_path.rglob("state.db")) == [tmp_path / ".fuente" / "state.db"]
    finally:
        reopened.close()


@pytest.mark.parametrize("key", ["chat", "catalog", "unknown"])
def test_ui_state_rejects_unknown_keys(tmp_path, key) -> None:
    with JobStore(tmp_path) as store:
        with pytest.raises(ValueError, match="key"):
            UIStateStore(store).set("persistent", "main-window", key, "value")


def test_ui_state_rejects_values_larger_than_64_kib(tmp_path) -> None:
    with JobStore(tmp_path) as store:
        with pytest.raises(ValueError, match="64 KiB"):
            UIStateStore(store).set("persistent", "main-window", "drafts", "x" * 65537)


def test_expired_session_state_is_removed(tmp_path) -> None:
    with JobStore(tmp_path) as store:
        state = UIStateStore(store)
        state.set("session", "job-queue", "cursor", {"current": "next"})
        store._connection.execute(
            "UPDATE ui_state SET expires_at = ? WHERE scope = 'session'",
            ("2000-01-01T00:00:00+00:00",),
        )
        assert state.get("session", "job-queue", "cursor") is None
        assert store._connection.execute(
            "SELECT COUNT(*) FROM ui_state WHERE scope = 'session'"
        ).fetchone()[0] == 0


def test_ui_state_schema_does_not_create_a_second_database(tmp_path) -> None:
    with JobStore(tmp_path) as store, sqlite3.connect(store.db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"ui_state", "transition_approvals", "review_claims"} <= tables
    assert list(tmp_path.rglob("*.db")) == [tmp_path / ".fuente" / "state.db"]


def test_bridge_round_trips_ui_state_through_existing_job_store(tmp_path) -> None:
    with JobStore(tmp_path) as store:
        backend = SimpleNamespace(
            get_notes_service=lambda: SimpleNamespace(job_store=store)
        )
        api = FuentePyWebViewApi(backend)
        assert api.set_ui_state(
            "persistent", "reader", "filters", {"search": "SQLite"}
        ) == {"status": "saved"}
        assert api.get_ui_state("persistent", "reader", "filters") == {
            "value": {"search": "SQLite"}
        }


def test_console_keeps_business_state_out_of_local_storage() -> None:
    html = (Path(__file__).parents[1] / "consola_preview.html").read_text(
        encoding="utf-8"
    )
    assert "localStorage.getItem" not in html
    assert "localStorage.setItem" not in html
    assert "localStorage.removeItem('fuente.visual-style')" in html
    assert "api.get_ui_state" in html
    assert "api.set_ui_state" in html
