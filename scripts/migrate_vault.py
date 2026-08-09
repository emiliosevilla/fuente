#!/usr/bin/env python3
"""CLI for Vault frontmatter migration (Task 8.4)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from funes.infrastructure.vault_migration import MigrationBlockedError, VaultMigrator  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate legacy Vault notes to frontmatter schema v1."
    )
    parser.add_argument("vault", type=Path, help="Path to the Vault root")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report findings without modifying the Vault",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply migration using a new or resumed manifest",
    )
    mode.add_argument(
        "--rollback",
        metavar="MANIFEST",
        type=Path,
        help="Restore pre-migration content from a migration manifest",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Resume or target a specific manifest path (with --apply)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Apply despite blocking scan findings (unsafe paths are still excluded)",
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Skip Chroma index rebuild after migration",
    )
    parser.add_argument(
        "--skip-moc",
        action="store_true",
        help="Skip MOC rebuild after migration",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    vault_path = args.vault.resolve()
    if not vault_path.is_dir():
        print(f"Vault not found: {vault_path}", file=sys.stderr)
        return 2

    migrator = VaultMigrator(vault_path)

    if args.dry_run:
        report = migrator.dry_run()
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return 0

    if args.rollback:
        try:
            manifest, restored_count = migrator.rollback(args.rollback.resolve())
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "status": manifest.status,
                    "manifest": str(args.rollback.resolve()),
                    "entries_restored": restored_count,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    try:
        manifest = migrator.apply(
            args.manifest.resolve() if args.manifest else None,
            rebuild_index=not args.skip_index,
            rebuild_moc=not args.skip_moc,
            force=args.force,
        )
    except MigrationBlockedError as error:
        print(str(error), file=sys.stderr)
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "blocking_findings": [finding.kind for finding in error.findings],
                },
                indent=2,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1

    manifest_path = (
        args.manifest.resolve()
        if args.manifest
        else migrator._manifest_file(manifest)
    )
    print(
        json.dumps(
            {
                "status": manifest.status,
                "manifest": str(manifest_path),
                "entries_applied": sum(1 for entry in manifest.entries if entry.applied),
                "moc_rebuilt": manifest.moc_rebuilt,
                "index_rebuilt": manifest.index_rebuilt,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
