from __future__ import annotations

import zipfile

import pytest

from fuente import runtime_loader


def test_runtime_source_payload_is_extracted_below_app_support(tmp_path, monkeypatch):
    payload = tmp_path / "runtime-source.zip"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("fuente/main.py", "VALUE = 1\n")
    monkeypatch.setattr(runtime_loader, "runtime_root", lambda: tmp_path / "runtime")
    monkeypatch.setattr(runtime_loader, "_bundle_file", lambda _name: payload)

    source = runtime_loader.runtime_source_dir()

    assert (source / "fuente" / "main.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_capability_install_uses_target_directory_and_reports_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_loader, "site_packages_dir", lambda: tmp_path / "site-packages")
    monkeypatch.setattr(runtime_loader, "_installed", lambda _capability: False)

    with pytest.raises(runtime_loader.RuntimeCapabilityError, match="No se pudo instalar"):
        runtime_loader.ensure_capability("audio", allow_download=True, installer=lambda _args: 1)

    assert (tmp_path / "site-packages").is_dir()


def test_pip_import_failure_is_reported_as_recoverable_capability_error(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_loader, "site_packages_dir", lambda: tmp_path / "site-packages")
    monkeypatch.setattr(runtime_loader, "_installed", lambda _capability: False)

    def broken_installer(_arguments):
        raise ModuleNotFoundError("colorsys")

    with pytest.raises(
        runtime_loader.RuntimeCapabilityError,
        match="instalador de capacidades no puede cargarse",
    ):
        runtime_loader.ensure_capability(
            "audio", allow_download=True, installer=broken_installer
        )
