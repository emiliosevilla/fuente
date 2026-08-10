"""Explicit, offline, collision-safe first-run onboarding."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal, Mapping

from funes.domain.frontmatter import ALLOWED_STATUSES, FrontmatterError, parse_frontmatter
from funes.domain.paths import AuthorizedPathResolver
from funes.infrastructure.atomic_files import atomic_write_json, atomic_write_text


OnboardingMarkerStatus = Literal["pending", "dismissed", "demo_installed"]
DemoResultStatus = Literal["demo_installed", "blocked"]
_WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class OnboardingStatus:
    status: OnboardingMarkerStatus
    show_first_run_panel: bool
    demo_version: str | None = None
    updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "show_first_run_panel": self.show_first_run_panel,
            "demo_version": self.demo_version,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class DemoVaultResult:
    status: DemoResultStatus
    created_paths: tuple[str, ...] = ()
    already_identical_paths: tuple[str, ...] = ()
    collisions: tuple[str, ...] = ()
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "created_paths": list(self.created_paths),
            "already_identical_paths": list(self.already_identical_paths),
            "collisions": list(self.collisions),
            "message": self.message,
        }


@dataclass(frozen=True)
class _PreparedNote:
    destination: str
    path: Path
    content: str
    classification: Literal["create", "already-identical"]


@dataclass(frozen=True)
class _FileSnapshot:
    existed: bool
    content: bytes | None


class OnboardingService:
    """Install the packaged demo only after a complete, read-only preflight."""

    MARKER_SCHEMA_VERSION = 1
    _RESOURCE_PACKAGE = "funes.resources.demo_vault"

    def __init__(
        self,
        vault_path: str | Path,
        *,
        path_resolver: AuthorizedPathResolver | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.vault_path = Path(vault_path).resolve()
        self._resolver = path_resolver or self._build_resolver()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _build_resolver(self) -> AuthorizedPathResolver:
        return AuthorizedPathResolver(
            vault_root=self.vault_path,
            output=self.vault_path / "4_salida",
            input=self.vault_path / "1_entrada",
            dirty=self.vault_path / "2_sucio",
            clean=self.vault_path / "3_limpio",
            quarantine=self.vault_path / ".funes" / "quarantine",
        )

    def _marker_path(self) -> Path:
        return self._resolver.resolve(".funes/onboarding.json", root_name="vault")

    def status(self, *, show_first_run_panel: bool | None = None) -> OnboardingStatus:
        """Read the marker; an absent marker is the non-writing pending state."""
        marker = self._marker_path()
        data: Mapping[str, Any] = {}
        if marker.is_file():
            try:
                loaded = json.loads(marker.read_text(encoding="utf-8"))
                if isinstance(loaded, Mapping):
                    data = loaded
            except (OSError, UnicodeError, json.JSONDecodeError):
                data = {}

        raw_status = data.get("status")
        status: OnboardingMarkerStatus = (
            raw_status
            if raw_status in {"pending", "dismissed", "demo_installed"}
            else "pending"
        )
        return OnboardingStatus(
            status=status,
            show_first_run_panel=(
                status == "pending"
                if show_first_run_panel is None
                else bool(show_first_run_panel)
            ),
            demo_version=(
                data.get("demo_version")
                if isinstance(data.get("demo_version"), str)
                else None
            ),
            updated_at=(
                data.get("updated_at")
                if isinstance(data.get("updated_at"), str)
                else None
            ),
        )

    def reopen(self) -> OnboardingStatus:
        """Return a transient Help-triggered panel without changing the marker."""
        current = self.status()
        return OnboardingStatus(
            status=current.status,
            show_first_run_panel=True,
            demo_version=current.demo_version,
            updated_at=current.updated_at,
        )

    def dismiss(self) -> OnboardingStatus:
        current = self.status()
        if current.status == "demo_installed":
            return current
        self._write_marker("dismissed", demo_version=current.demo_version)
        return self.status()

    def install_demo_vault(self) -> DemoVaultResult:
        current = self.status()
        if current.status == "demo_installed":
            return DemoVaultResult(
                status="demo_installed",
                message="El Vault demo ya estaba instalado; no se realizaron cambios.",
            )

        try:
            manifest, prepared, collisions = self._preflight()
        except (OSError, UnicodeError, ValueError, FrontmatterError) as error:
            return DemoVaultResult(
                status="blocked",
                message=f"No se puede instalar el Vault demo: {error}",
            )

        if collisions:
            return DemoVaultResult(
                status="blocked",
                collisions=tuple(collisions),
                message=(
                    "Instalación bloqueada: resuelve estas colisiones sin sobrescribir "
                    "documentos existentes."
                ),
            )

        created: list[str] = []
        identical: list[str] = []
        attempted_notes: list[tuple[Path, bytes]] = []
        created_directories: list[Path] = []
        marker_path = self._marker_path()
        marker_snapshot: _FileSnapshot | None = None
        marker_payload: dict[str, Any] | None = None
        try:
            marker_snapshot = self._snapshot_file(marker_path)
            marker_payload = self._marker_payload(
                "demo_installed", demo_version=manifest["demo_version"]
            )
            for item in prepared:
                if item.classification == "already-identical":
                    identical.append(item.destination)
                    continue
                if item.path.exists():
                    raise OSError(
                        f"demo destination appeared after preflight: {item.destination}"
                    )
                self._ensure_parent(item.path, created_directories)
                if item.path.exists():
                    raise OSError(
                        f"demo destination appeared after preflight: {item.destination}"
                    )
                expected_content = item.content.encode("utf-8")
                attempted_notes.append((item.path, expected_content))
                atomic_write_text(item.path, item.content)
                created.append(item.destination)

            self._ensure_parent(marker_path, created_directories)
            atomic_write_json(marker_path, marker_payload)
        except Exception as error:
            rollback_errors = self._rollback_install(
                attempted_notes,
                marker_path,
                marker_snapshot,
                marker_payload,
                created_directories,
            )
            detail = f"Instalación revertida: {error}"
            if rollback_errors:
                detail += " (rollback incompleto: " + "; ".join(rollback_errors) + ")"
            return DemoVaultResult(status="blocked", message=detail)

        return DemoVaultResult(
            status="demo_installed",
            created_paths=tuple(created),
            already_identical_paths=tuple(identical),
            message="Vault demo creado sin sobrescribir documentos existentes.",
        )

    def _preflight(self) -> tuple[dict[str, Any], list[_PreparedNote], list[str]]:
        manifest = self._read_manifest()
        notes = manifest.get("notes")
        if not isinstance(notes, list) or not notes:
            raise ValueError("manifest notes must be a non-empty ordered list")

        prepared: list[_PreparedNote] = []
        collisions: list[str] = []
        destinations: set[str] = set()
        planned_by_name: dict[str, list[str]] = {}
        review_statuses: list[str] = []
        for entry in notes:
            if not isinstance(entry, Mapping):
                raise ValueError("manifest note entry must be an object")
            source_name = self._safe_resource_name(entry.get("source_resource"))
            destination = self._safe_destination(entry.get("destination"))
            if destination in destinations:
                collisions.append(destination)
                continue
            destinations.add(destination)

            source = resources.files(self._RESOURCE_PACKAGE).joinpath(source_name)
            if not source.is_file():
                raise ValueError(f"missing bundled resource: {source_name}")
            raw = source.read_bytes()
            expected_hash = entry.get("sha256")
            if not isinstance(expected_hash, str) or not _SHA256_PATTERN.fullmatch(
                expected_hash
            ):
                raise ValueError(f"invalid SHA-256 for {source_name}")
            if hashlib.sha256(raw).hexdigest() != expected_hash:
                raise ValueError(f"SHA-256 mismatch for {source_name}")
            content = raw.decode("utf-8")
            metadata, body = parse_frontmatter(content)
            expected_status = entry.get("expected_initial_review_status")
            if expected_status not in ALLOWED_STATUSES:
                raise ValueError(f"invalid initial review status for {source_name}")
            if metadata["status"] != expected_status:
                raise ValueError(f"frontmatter status mismatch for {source_name}")
            if metadata["issue"] != manifest["issue"]:
                raise ValueError(f"frontmatter issue mismatch for {source_name}")
            review_statuses.append(metadata["status"])

            actual_links = [
                self._clean_wikilink(match) for match in _WIKILINK_PATTERN.findall(body)
            ]
            expected_links = entry.get("expected_wikilinks")
            if not isinstance(expected_links, list) or not all(
                isinstance(link, str) for link in expected_links
            ):
                raise ValueError(f"invalid expected wikilinks for {source_name}")
            if actual_links != expected_links:
                raise ValueError(f"wikilink mismatch for {source_name}")
            planned_by_name.setdefault(Path(destination).stem, []).append(destination)

            try:
                target = self._resolver.resolve_note(destination)
            except Exception:
                collisions.append(destination)
                continue
            if target.exists():
                try:
                    identical = target.is_file() and target.read_bytes() == raw
                except OSError:
                    identical = False
                classification = "already-identical" if identical else "collision"
                if classification == "collision":
                    collisions.append(destination)
                    continue
            else:
                classification = "create"
            prepared.append(_PreparedNote(destination, target, content, classification))

        if review_statuses.count("pending_review") != 1:
            raise ValueError("demo manifest must contain exactly one pending_review note")

        for entry in notes:
            source_name = self._safe_resource_name(entry.get("source_resource"))
            for link in entry.get("expected_wikilinks", []):
                candidates = planned_by_name.get(Path(link).stem, [])
                if "/" in link:
                    candidates = [
                        destination
                        for destination in candidates
                        if PurePosixPath(destination)
                        .with_suffix("")
                        .as_posix()
                        .endswith(link)
                    ]
                if len(candidates) != 1:
                    collisions.append(f"{source_name}: [[{link}]]")
                    continue
                try:
                    self._resolver.resolve_note(candidates[0])
                except Exception:
                    collisions.append(f"{source_name}: [[{link}]]")

        return manifest, prepared, sorted(set(collisions))

    def _read_manifest(self) -> dict[str, Any]:
        raw = resources.files(self._RESOURCE_PACKAGE).joinpath("manifest.json").read_text(
            encoding="utf-8"
        )
        manifest = json.loads(raw)
        if not isinstance(manifest, dict):
            raise ValueError("manifest root must be an object")
        if manifest.get("schema_version") != self.MARKER_SCHEMA_VERSION:
            raise ValueError("unsupported manifest schema_version")
        for field in ("demo_version", "theme", "issue"):
            if not isinstance(manifest.get(field), str) or not manifest[field].strip():
                raise ValueError(f"manifest {field} is required")
        return manifest

    @staticmethod
    def _safe_resource_name(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("source_resource is required")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("source_resource must stay inside the resource bundle")
        return path.as_posix()

    @staticmethod
    def _safe_destination(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("destination is required")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".md":
            raise ValueError("destination must be a safe Markdown Vault-relative path")
        return path.as_posix()

    @staticmethod
    def _clean_wikilink(value: str) -> str:
        return value.split("|", 1)[0].split("#", 1)[0].strip()

    @staticmethod
    def _snapshot_file(path: Path) -> _FileSnapshot:
        if not path.exists():
            return _FileSnapshot(False, None)
        if not path.is_file():
            return _FileSnapshot(True, None)
        return _FileSnapshot(True, path.read_bytes())

    @staticmethod
    def _ensure_parent(path: Path, created_directories: list[Path]) -> None:
        missing: list[Path] = []
        current = path.parent
        while not current.exists():
            missing.append(current)
            if current == current.parent:
                break
            current = current.parent
        path.parent.mkdir(parents=True, exist_ok=True)
        created_directories.extend(reversed(missing))

    @staticmethod
    def _marker_bytes(payload: Mapping[str, Any]) -> bytes:
        return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

    def _rollback_install(
        self,
        attempted_notes: list[tuple[Path, bytes]],
        marker_path: Path,
        marker_snapshot: _FileSnapshot | None,
        marker_payload: Mapping[str, Any] | None,
        created_directories: list[Path],
    ) -> list[str]:
        errors: list[str] = []
        for path, expected_content in reversed(attempted_notes):
            try:
                if path.is_file() and path.read_bytes() == expected_content:
                    path.unlink()
            except OSError as error:
                errors.append(f"{path}: {error}")

        if marker_snapshot is not None and marker_payload is not None:
            try:
                expected_marker = self._marker_bytes(marker_payload)
                if marker_path.is_file() and marker_path.read_bytes() == expected_marker:
                    if marker_snapshot.existed:
                        if marker_snapshot.content is not None:
                            marker_path.write_bytes(marker_snapshot.content)
                    else:
                        marker_path.unlink()
            except OSError as error:
                errors.append(f"{marker_path}: {error}")

        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                # Existing or human-populated directories are never removed.
                pass
        return errors

    def _marker_payload(
        self, status: OnboardingMarkerStatus, *, demo_version: str | None
    ) -> dict[str, Any]:
        return {
            "schema_version": self.MARKER_SCHEMA_VERSION,
            "status": status,
            "demo_version": demo_version,
            "updated_at": self._clock().astimezone(timezone.utc).isoformat(),
        }

    def _write_marker(
        self, status: OnboardingMarkerStatus, *, demo_version: str | None
    ) -> None:
        atomic_write_json(
            self._marker_path(),
            self._marker_payload(status, demo_version=demo_version),
        )
