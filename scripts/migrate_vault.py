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

from fuente.infrastructure.fuente_migration import (  # noqa: E402
    InventoryOutputError,
    V3MigrationBlockedError,
    apply_v3_migration,
    build_inventory,
    plan_v3_migration,
    rollback_v3_migration,
    validate_inventory_output,
    write_inventory,
    write_v3_manifest,
)
from fuente.infrastructure.taxonomy_migration import (  # noqa: E402
    TaxonomyBlockedError,
    TaxonomyMigrator,
    apply_sumarios_migration,
    rollback_sumarios_migration,
)
from fuente.infrastructure.vault_migration import MigrationBlockedError, VaultMigrator  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate legacy Vault notes to frontmatter schema v1."
    )
    parser.add_argument("vault", nargs="?", type=Path, help="Path to the Vault root")
    parser.add_argument("--vault", dest="vault_option", type=Path, help="Path to the Vault root")
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
    mode.add_argument(
        "--taxonomy-dry-run",
        action="store_true",
        help="Plan the approved physical 4_salida taxonomy without moving files",
    )
    mode.add_argument(
        "--taxonomy-apply",
        action="store_true",
        help="Apply or resume the physical 4_salida taxonomy migration",
    )
    mode.add_argument(
        "--taxonomy-normalize",
        action="store_true",
        help="Add reversible schema-v2 identity metadata before taxonomy movement",
    )
    mode.add_argument(
        "--taxonomy-rollback",
        metavar="MANIFEST",
        type=Path,
        help="Rollback a physical 4_salida taxonomy migration",
    )
    mode.add_argument(
        "--taxonomy-normalize-rollback",
        metavar="MANIFEST",
        type=Path,
        help="Rollback legacy-note normalization",
    )
    mode.add_argument(
        "--sumarios-dry-run",
        action="store_true",
        help="Plan v3 summary moves to 4_salida/Sumarios without moving notes",
    )
    mode.add_argument(
        "--sumarios-approve",
        action="store_true",
        help="Record the explicit human approval required by a Sumarios manifest",
    )
    mode.add_argument(
        "--sumarios-apply",
        action="store_true",
        help="Apply an approved physical Fuentes-to-Sumarios manifest",
    )
    mode.add_argument(
        "--sumarios-rollback",
        action="store_true",
        help="Rollback an applied physical Fuentes-to-Sumarios manifest",
    )
    mode.add_argument(
        "--fuente-inventory",
        action="store_true",
        help="Create a read-only Fuente migration inventory",
    )
    mode.add_argument(
        "--fuente-v3-plan",
        metavar="MANIFEST",
        type=Path,
        help="Plan the v2-to-v3 frontmatter migration without changing the Vault",
    )
    mode.add_argument(
        "--fuente-v3-apply",
        metavar="MANIFEST",
        type=Path,
        help="Apply a reviewed Fuente v3 manifest",
    )
    mode.add_argument(
        "--fuente-v3-rollback",
        metavar="MANIFEST",
        type=Path,
        help="Rollback a previously applied Fuente v3 manifest",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path for --fuente-inventory",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Resume or target a specific manifest path",
    )
    parser.add_argument(
        "--reviewer",
        help="Human reviewer recorded by --sumarios-approve",
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


def _manifest_matches_vault(manifest_path: Path, vault_path: Path) -> bool:
    """Bind an untrusted manifest argument to the Vault selected by the user."""
    target = manifest_path.expanduser().absolute()
    if target.is_symlink() or not target.is_file():
        return False
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        declared = Path(payload["vault_root"]).expanduser().absolute()
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return declared == vault_path


def _sumarios_manifest_matches_vault(manifest_path: Path, vault_path: Path) -> bool:
    target = manifest_path.expanduser().absolute()
    if target.is_symlink() or not target.is_file():
        return False
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        declared = Path(payload["vault_path"]).expanduser().resolve()
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return declared == vault_path


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    vault_arg = args.vault_option or args.vault
    if vault_arg is None:
        print("Vault path is required", file=sys.stderr)
        return 2
    if args.fuente_inventory and args.output is None:
        print("--output is required with --fuente-inventory", file=sys.stderr)
        return 2
    vault_lexical = vault_arg.expanduser().absolute()
    fuente_v3_mode = bool(
        args.fuente_v3_plan
        or args.fuente_v3_apply
        or args.fuente_v3_rollback
    )
    if (args.fuente_inventory or fuente_v3_mode) and vault_lexical.is_symlink():
        print("Vault root must not be a symlink", file=sys.stderr)
        return 2
    vault_path = vault_lexical.resolve()
    if not vault_path.is_dir():
        print(f"Vault not found: {vault_path}", file=sys.stderr)
        return 2

    if args.fuente_inventory:
        try:
            output_path = validate_inventory_output(args.output, vault_lexical)
        except InventoryOutputError as error:
            print(str(error), file=sys.stderr)
            return 2
        inventory = build_inventory(vault_path, REPO_ROOT)
        try:
            write_inventory(output_path, inventory)
        except FileExistsError as error:
            print(str(error), file=sys.stderr)
            return 2
        print(json.dumps(inventory.to_dict(), indent=2, ensure_ascii=False))
        return 0 if inventory.is_safe_to_apply else 1

    sumarios_mode = bool(
        args.sumarios_dry_run or args.sumarios_approve or args.sumarios_apply or args.sumarios_rollback
    )
    if sumarios_mode:
        taxonomy = TaxonomyMigrator(vault_path)
        if args.sumarios_dry_run:
            manifest = taxonomy.plan_sumarios()
            if args.manifest:
                try:
                    taxonomy.persist_sumarios_plan(args.manifest, manifest)
                except (FileExistsError, OSError, ValueError) as error:
                    print(str(error), file=sys.stderr)
                    return 2
            print(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
            return 1 if manifest.status == "blocked" else 0
        if args.manifest is None:
            print("--manifest is required for Sumarios approval, apply and rollback", file=sys.stderr)
            return 2
        if not _sumarios_manifest_matches_vault(args.manifest, vault_path):
            print("Manifest Vault does not match --vault", file=sys.stderr)
            return 2
        try:
            if args.sumarios_approve:
                if not args.reviewer:
                    print("--reviewer is required with --sumarios-approve", file=sys.stderr)
                    return 2
                manifest = taxonomy.approve_sumarios_manifest(args.manifest, args.reviewer)
            elif args.sumarios_apply:
                manifest = apply_sumarios_migration(args.manifest)
            else:
                manifest = rollback_sumarios_migration(args.manifest)
        except (TaxonomyBlockedError, ValueError, OSError) as error:
            print(str(error), file=sys.stderr)
            return 1
        print(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
        return 0

    if args.fuente_v3_plan:
        manifest = plan_v3_migration(build_inventory(vault_path, REPO_ROOT))
        try:
            write_v3_manifest(args.fuente_v3_plan, manifest)
        except (FileExistsError, InventoryOutputError, OSError) as error:
            print(str(error), file=sys.stderr)
            return 2
        payload = manifest.to_dict()
        payload["manifest"] = str(args.fuente_v3_plan.expanduser().absolute())
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1 if manifest.status == "blocked" else 0

    fuente_v3_manifest = args.fuente_v3_apply or args.fuente_v3_rollback
    if fuente_v3_manifest:
        if not _manifest_matches_vault(fuente_v3_manifest, vault_path):
            print("Manifest Vault does not match --vault", file=sys.stderr)
            return 2
        try:
            if args.fuente_v3_apply:
                manifest = apply_v3_migration(fuente_v3_manifest)
            else:
                manifest = rollback_v3_migration(fuente_v3_manifest)
        except V3MigrationBlockedError as error:
            print(str(error), file=sys.stderr)
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "blocking_findings": [
                            finding.kind for finding in error.findings
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 1
        payload = manifest.to_dict()
        payload["manifest"] = str(fuente_v3_manifest.expanduser().absolute())
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    migrator = VaultMigrator(vault_path)

    taxonomy = TaxonomyMigrator(vault_path)
    if args.taxonomy_dry_run:
        manifest = taxonomy.plan()
        print(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
        return 1 if manifest.status == "blocked" else 0
    if args.taxonomy_normalize_rollback:
        try:
            manifest = taxonomy.rollback_normalization(
                args.taxonomy_normalize_rollback.resolve()
            )
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.taxonomy_normalize:
        try:
            manifest = taxonomy.normalize_legacy_notes(
                args.manifest.resolve() if args.manifest else None
            )
        except TaxonomyBlockedError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.taxonomy_rollback:
        try:
            manifest = taxonomy.rollback(args.taxonomy_rollback.resolve())
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.taxonomy_apply:
        try:
            manifest = taxonomy.apply(
                args.manifest.resolve() if args.manifest else None
            )
        except TaxonomyBlockedError as error:
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
        print(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
        return 0

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
