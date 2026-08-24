"""Regenerate P-01 candidates in an isolated copy of a Fuente Vault.

This helper only copies the three declared dirty originals and writes Markdown
under the supplied temporary output root. It does not open SQLite, approve
notes, modify the real Vault, or run any downstream derivation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.domain.paths import document_id_for_relative_path
from fuente.extractors.base import enrich_extraction_metadata
from fuente.extractors.registry import ExtractorRegistry


SOURCE_NAMES = (
    "Aptis - Certificado C1_6b6b3d97.pdf",
    "ESP - Sevilla enero 2025 Aptis ESOL_87f7a10b.pdf",
    "Aptis - Certificado C1_1ed323ae.jpg",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _candidate_filename(source_name: str) -> str:
    source = Path(source_name)
    return f"{source.stem}_{source.suffix.lstrip('.').lower()}.md"


def regenerate_p01_candidates(source_vault: Path, output_root: Path) -> list[dict[str, Any]]:
    """Copy the P-01 inputs and create only useful, reviewable originals."""
    source_root = source_vault.expanduser().resolve()
    destination_root = output_root.expanduser().resolve()
    if not source_root.is_dir():
        raise ValueError(f"source Vault is not a directory: {source_root}")
    if destination_root == source_root or destination_root.is_relative_to(source_root):
        raise ValueError("output root must not be the source Vault or inside it")
    if source_root.is_relative_to(destination_root):
        raise ValueError("output root must not contain the source Vault")
    if output_root.is_symlink():
        raise ValueError("output root must not be a symlink")
    if output_root.exists() and (not output_root.is_dir() or any(output_root.iterdir())):
        raise ValueError("output root must be a new or empty directory")
    dirty_dir = output_root / "Vault_Fuente_P01" / "2_copiado"
    clean_dir = output_root / "Vault_Fuente_P01" / "3_capturado"
    dirty_dir.mkdir(parents=True, exist_ok=True)
    clean_dir.mkdir(parents=True, exist_ok=True)
    registry = ExtractorRegistry()
    records: list[dict[str, Any]] = []

    for source_name in SOURCE_NAMES:
        source = source_root / "2_copiado" / source_name
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"source input must be a regular file: {source}")
        copied = dirty_dir / source_name
        shutil.copy2(source, copied)
        source_hash = _sha256(copied)
        result = registry.extract(copied)
        record: dict[str, Any] = {
            "source": f"2_copiado/{source_name}",
            "sha256": source_hash,
            "bytes": copied.stat().st_size,
            "extraction_status": result.status,
            "extraction_reason": result.reason,
            "extraction_method": result.metadata.get("extraction_method"),
            "candidate": None,
        }
        if result.status == "completed" and result.content and result.content.strip():
            candidate_relative = f"3_capturado/{_candidate_filename(source_name)}"
            candidate_path = output_root / "Vault_Fuente_P01" / candidate_relative
            metadata = {
                "schema_version": 3,
                "note_id": document_id_for_relative_path(candidate_relative),
                "note_type": "original",
                "title": Path(source_name).stem,
                "date": "",
                "author": "",
                "tags": ["extracción", "p01"],
                "issue": "_Sin_Cuestion",
                "status": "pending_review",
                "history": [],
                "origins": [],
                **dict(result.metadata),
            }
            metadata = enrich_extraction_metadata(metadata, result.content)
            metadata.update(
                {
                    "schema_version": 3,
                    "note_id": document_id_for_relative_path(candidate_relative),
                    "note_type": "original",
                    "status": "pending_review",
                    "origins": [],
                }
            )
            markdown = serialize_frontmatter(metadata, human_labels=True) + result.content.strip() + "\n"
            parse_frontmatter(markdown)
            candidate_path.write_text(markdown, encoding="utf-8")
            record["candidate"] = {
                "path": candidate_relative,
                "status": "pending_review",
                "note_type": "original",
                "sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
                "bytes": len(markdown.encode("utf-8")),
                "useful_extraction": True,
            }
        else:
            record["state"] = "blocked_ocr_or_extraction"
        records.append(record)

    manifest = output_root / "p01-candidates.json"
    manifest.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    records = regenerate_p01_candidates(args.vault, args.output_root)
    for record in records:
        candidate = record["candidate"]
        state = candidate["status"] if candidate else record["state"]
        print(f"{record['source']}|{record['sha256']}|{state}")
    print(f"manifest={args.output_root / 'p01-candidates.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
