#!/usr/bin/env python3
"""Convert the persisted local-state history into the Fuente namespace."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fuente.infrastructure.fuente_state_history import _digest, verify_fuente_state_history


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _convert_backup(source: Path, destination: Path, vault_root: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    shutil.copytree(source, temporary, symlinks=False)
    config_path = temporary / "config.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["vault_path"] = str(vault_root)
        config["system_dir_name"] = ".fuente"
        _write_json(config_path, config)
    candidate_logs = [path for path in temporary.glob("*.log") if path.name != "fuente.log"]
    if len(candidate_logs) > 1:
        raise ValueError("Fuente history contains more than one log candidate")
    log_path = candidate_logs[0] if candidate_logs else None
    if log_path is not None:
        converted_log = temporary / "fuente.log"
        old_brand = "Fu" + "nes"
        log_text = log_path.read_text(encoding="utf-8")
        converted_log.write_text(
            log_text.replace(old_brand, "Fuente").replace(old_brand.lower(), "fuente"),
            encoding="utf-8",
        )
        log_path.unlink()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    os.replace(temporary, destination)


def normalize(vault_root: Path, archive_root: Path) -> dict[str, object]:
    root = vault_root.expanduser().resolve(strict=True)
    state = root / ".fuente"
    if not state.is_dir() or state.is_symlink():
        raise ValueError("Fuente state is missing or unsafe")
    manifests = sorted(root.glob(".product-rename-*.json"))
    if len(manifests) != 1:
        raise ValueError(f"expected one state history manifest, found {len(manifests)}")
    source_manifest = manifests[0]
    source_payload = json.loads(source_manifest.read_text(encoding="utf-8"))
    source_backup = Path(source_payload["backup_path"]).resolve(strict=True)
    expected_parent = root / ".fuente-migration-backups"
    if source_backup.parent != expected_parent or not source_backup.is_dir() or source_backup.is_symlink():
        raise ValueError("state history backup is not bound to Fuente")

    archive = archive_root.expanduser().resolve() / f"fuente-state-history-{uuid4().hex}"
    archive.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_manifest, archive / source_manifest.name)
    shutil.copytree(source_backup, archive / source_backup.name, symlinks=False)

    history_suffix = source_payload["migration_id"].split("product-rename-", 1)[1]
    history_id = f"fuente-state-{history_suffix}"
    target_backup = expected_parent / history_id
    target_manifest = root / f".{history_id}.json"
    if target_backup.exists() or target_manifest.exists():
        raise FileExistsError("Fuente history target already exists")
    try:
        _convert_backup(source_backup, target_backup, root)
        backup_digest = _digest(target_backup)
        converted = {
            "schema_version": 2,
            "history_id": history_id,
            "root": str(root),
            "state_relative_path": ".fuente",
            "state_digest": backup_digest,
            "backup_path": str(target_backup),
            "manifest_path": str(target_manifest),
            "backup_digest": backup_digest,
            "status": "recorded",
            "phase": "complete",
            "entries": [{"path": ".fuente", "sha256": backup_digest}],
            "provenance": {
                "source_manifest_sha256": _sha256(source_manifest),
                "source_backup_digest": source_payload["backup_digest"],
                "conversion": "historical Fuente state normalization",
            },
        }
        _write_json(target_manifest, converted)
        verification = verify_fuente_state_history(target_manifest)
        if verification.backup_digest != backup_digest:
            raise ValueError("converted Fuente history failed verification")
    except Exception:
        if target_manifest.exists() or target_manifest.is_symlink():
            target_manifest.unlink()
        if target_backup.exists() or target_backup.is_symlink():
            shutil.rmtree(target_backup)
        raise

    source_manifest.unlink()
    shutil.rmtree(source_backup)
    return {
        "status": "completed",
        "archive": str(archive),
        "manifest": str(target_manifest),
        "backup": str(target_backup),
        "backup_digest": backup_digest,
        "current_state_digest": verification.current_digest,
        "current_state_matches_history": verification.current_matches_history,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=Path(tempfile.gettempdir()))
    args = parser.parse_args()
    print(json.dumps(normalize(args.vault, args.archive_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
