"""Approval records bound to one exact canonical Markdown revision."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Protocol
from uuid import UUID

from fuente.domain.documents import MarkdownDocument, NoteDocument
from fuente.domain.errors import NoteRevisionConflictError, PathAuthorizationError
from fuente.domain.frontmatter import FrontmatterError


MAX_REVIEWER_CHARS = 80
TRANSITION_STAGES = (
    "1_volcado",
    "2_copiado",
    "3_capturado",
    "4_procesado",
    "5_compartido",
)


class ApprovalStore(Protocol):
    """Storage operations required by the approval domain facade."""

    def get_note(self, note_id: str) -> dict[str, Any] | None: ...

    def approve_note_revision(
        self,
        *,
        note_id: str,
        expected_revision: int,
        expected_content_hash: str,
        reviewer: str,
    ) -> dict[str, Any] | None: ...

    def is_note_approval_current(
        self, note_id: str, revision: int, content_hash: str
    ) -> bool: ...

    def invalidate_note_approval(
        self,
        *,
        note_id: str,
        new_content_hash: str,
        derived_note_ids: list[str],
    ) -> int: ...


def validate_approval_note_id(value: object) -> str:
    """Return one canonical opaque UUID and reject anything path-shaped."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("note_id is required")
    note_id = value.strip()
    if (
        "/" in note_id
        or "\\" in note_id
        or note_id.endswith(".md")
        or "\x00" in note_id
    ):
        raise PathAuthorizationError()
    try:
        parsed = UUID(note_id)
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("note_id must be a UUID") from error
    if str(parsed) != note_id.lower():
        raise ValueError("note_id must be a canonical UUID")
    return note_id.lower()


def validate_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("revision must be a positive integer")
    return value


def validate_content_hash(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("content_hash must be a lowercase SHA-256 digest")
    return value


def normalize_reviewer(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("reviewer must be a string")
    reviewer = value.strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    if len(reviewer) > MAX_REVIEWER_CHARS:
        raise ValueError(f"reviewer exceeds {MAX_REVIEWER_CHARS} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in reviewer):
        raise ValueError("reviewer contains control characters")
    return reviewer


def validate_transition_identity(
    artifact_id: object,
    source_stage: object,
    target_stage: object,
    revision: object,
    content_hash: object,
) -> tuple[str, str, str, int, str]:
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        raise ValueError("artifact_id is required")
    if len(artifact_id) > 255 or any(ord(char) < 32 for char in artifact_id):
        raise ValueError("artifact_id is invalid")
    if not isinstance(source_stage, str) or not isinstance(target_stage, str):
        raise ValueError("transition stages must be strings")
    try:
        source_index = TRANSITION_STAGES.index(source_stage)
    except ValueError as error:
        raise ValueError("transition source is not supported") from error
    if (
        source_index + 1 >= len(TRANSITION_STAGES)
        or TRANSITION_STAGES[source_index + 1] != target_stage
    ):
        raise ValueError("transition must join adjacent pipeline stages")
    return (
        artifact_id.strip(),
        source_stage,
        target_stage,
        validate_revision(revision),
        validate_content_hash(content_hash),
    )


@dataclass(frozen=True)
class ReviewClaim:
    artifact_id: str
    source_stage: str
    target_stage: str
    revision: int
    content_hash: str
    reviewer: str
    claimed_at: str
    expires_at: str

    def __post_init__(self) -> None:
        validate_transition_identity(
            self.artifact_id,
            self.source_stage,
            self.target_stage,
            self.revision,
            self.content_hash,
        )
        normalize_reviewer(self.reviewer)
        claimed_at = datetime.fromisoformat(self.claimed_at)
        expires_at = datetime.fromisoformat(self.expires_at)
        if (
            claimed_at.tzinfo is None
            or expires_at.tzinfo is None
            or expires_at <= claimed_at
        ):
            raise ValueError("review claim timestamps are invalid")


@dataclass(frozen=True)
class TransitionApproval:
    artifact_id: str
    source_stage: str
    target_stage: str
    revision: int
    content_hash: str
    reviewer: str
    approved_at: str

    def __post_init__(self) -> None:
        validate_transition_identity(
            self.artifact_id,
            self.source_stage,
            self.target_stage,
            self.revision,
            self.content_hash,
        )
        normalize_reviewer(self.reviewer)
        approved_at = datetime.fromisoformat(self.approved_at)
        if approved_at.tzinfo is None:
            raise ValueError("approved_at must include a timezone")


@dataclass(frozen=True)
class ApprovalRecord:
    note_id: str
    revision: int
    content_hash: str
    reviewer: str
    approved_at: str

    def __post_init__(self) -> None:
        validate_approval_note_id(self.note_id)
        validate_revision(self.revision)
        validate_content_hash(self.content_hash)
        normalize_reviewer(self.reviewer)
        if not isinstance(self.approved_at, str) or not self.approved_at:
            raise ValueError("approved_at must be a server timestamp")
        try:
            timestamp = datetime.fromisoformat(self.approved_at)
        except ValueError as error:
            raise ValueError("approved_at must be an ISO-8601 timestamp") from error
        if timestamp.tzinfo is None:
            raise ValueError("approved_at must include a timezone")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalRequest:
    note_id: str
    relative_path: str
    revision: int
    content_hash: str

    def __post_init__(self) -> None:
        validate_approval_note_id(self.note_id)
        validate_revision(self.revision)
        validate_content_hash(self.content_hash)
        if not isinstance(self.relative_path, str) or not self.relative_path:
            raise ValueError("relative_path is required")


class ApprovalLedger:
    """Read approval state and invalidate it against canonical Markdown bytes."""

    def __init__(
        self,
        store: ApprovalStore,
        *,
        vault_root: Path | str,
        clean_root: Path | str,
        derived_root: Path | str,
    ) -> None:
        self.store = store
        self.vault_root = Path(vault_root).resolve()
        self.clean_root = Path(clean_root).resolve()
        self.derived_root = Path(derived_root).resolve()
        if not self.clean_root.is_relative_to(self.vault_root):
            raise PathAuthorizationError()
        if not self.derived_root.is_relative_to(self.vault_root):
            raise PathAuthorizationError()

    def approve(
        self,
        note_id: str,
        revision: int,
        content_hash: str,
        reviewer: str,
    ) -> ApprovalRecord:
        note_id = validate_approval_note_id(note_id)
        revision = validate_revision(revision)
        content_hash = validate_content_hash(content_hash)
        reviewer = normalize_reviewer(reviewer)
        row = self.store.approve_note_revision(
            note_id=note_id,
            expected_revision=revision,
            expected_content_hash=content_hash,
            reviewer=reviewer,
        )
        if row is None:
            raise NoteRevisionConflictError(note_id)
        return ApprovalRecord(
            note_id=str(row["note_id"]),
            revision=int(row["revision"]),
            content_hash=str(row["content_hash"]),
            reviewer=str(row["reviewer"]),
            approved_at=str(row["approved_at"]),
        )

    def is_current(self, note_id: str, revision: int, content_hash: str) -> bool:
        try:
            note_id = validate_approval_note_id(note_id)
            revision = validate_revision(revision)
            content_hash = validate_content_hash(content_hash)
        except (PathAuthorizationError, ValueError):
            return False
        if not self.store.is_note_approval_current(note_id, revision, content_hash):
            return False
        try:
            row, _path, document = self.canonical_snapshot(note_id)
        except (
            FrontmatterError,
            OSError,
            PathAuthorizationError,
            UnicodeError,
            ValueError,
        ):
            return False
        return (
            int(row["revision"]) == revision
            and str(row["content_hash"]) == content_hash
            and str(row["status"]) == "approved"
            and document.content_hash == content_hash
        )

    def invalidate_for_note(self, note_id: str) -> int:
        note_id = validate_approval_note_id(note_id)
        row, _path, document = self.canonical_snapshot(note_id)
        if str(row["content_hash"]) == document.content_hash:
            return 0
        return self.store.invalidate_note_approval(
            note_id=note_id,
            new_content_hash=document.content_hash,
            derived_note_ids=self._derived_note_ids(note_id),
        )

    def canonical_snapshot(
        self, note_id: str
    ) -> tuple[dict[str, Any], Path, NoteDocument]:
        """Load one catalogued clean note without accepting a caller path."""
        note_id = validate_approval_note_id(note_id)
        row = self.store.get_note(note_id)
        if row is None:
            raise PathAuthorizationError()
        relative_path = row.get("relative_path")
        path = self._authorized_markdown(relative_path, root=self.clean_root)
        markdown = path.read_text(encoding="utf-8")
        document = NoteDocument.from_persisted(
            document_id=note_id,
            relative_path=str(relative_path),
            markdown=markdown,
            revision=int(row["revision"]),
        )
        if document.note_id != note_id:
            raise PathAuthorizationError()
        return row, path, document

    def _authorized_markdown(self, relative_path: object, *, root: Path) -> Path:
        if not isinstance(relative_path, str) or not relative_path:
            raise PathAuthorizationError()
        if "\x00" in relative_path or "\\" in relative_path:
            raise PathAuthorizationError()
        posix = PurePosixPath(relative_path)
        windows = PureWindowsPath(relative_path)
        if (
            posix.is_absolute()
            or windows.is_absolute()
            or posix.suffix.lower() != ".md"
            or any(part in {"", ".", ".."} for part in posix.parts)
        ):
            raise PathAuthorizationError()

        lexical = self.vault_root.joinpath(*posix.parts)
        try:
            lexical.relative_to(root)
        except ValueError as error:
            raise PathAuthorizationError() from error
        current = self.vault_root
        for part in posix.parts:
            current = current / part
            if current.is_symlink():
                raise PathAuthorizationError()
        resolved = lexical.resolve(strict=False)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise PathAuthorizationError()
        return resolved

    def _derived_note_ids(self, origin_note_id: str) -> list[str]:
        if not self.derived_root.is_dir() or self.derived_root.is_symlink():
            return []
        connected: set[str] = set()
        for candidate in sorted(self.derived_root.rglob("*.md")):
            try:
                relative = candidate.relative_to(self.vault_root).as_posix()
                path = self._authorized_markdown(relative, root=self.derived_root)
                document = MarkdownDocument.from_markdown(
                    path.read_text(encoding="utf-8")
                )
            except (
                FrontmatterError,
                OSError,
                PathAuthorizationError,
                UnicodeError,
                ValueError,
            ):
                continue
            if document.note_id and any(
                origin.note_id == origin_note_id for origin in document.origins
            ):
                connected.add(document.note_id)
        return sorted(connected)
