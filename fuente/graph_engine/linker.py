"""WikiLink insertion that respects frontmatter, code fences, and nested notes."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence

from fuente.core.vault import document_id_for_relative_path
from fuente.domain.documents import MarkdownDocument
from fuente.domain.paths import REFLOW_REVIEW_DIR_NAME

logger = logging.getLogger(__name__)

CANONICAL_MOC_FILENAME = "_Indice_MOC.md"
_SYSTEM_DIR_NAME = ".fuente"
_CODE_PLACEHOLDER = "__FUENTE_CODE_BLOCK_{idx}__"
_WIKILINK_PLACEHOLDER = "__FUENTE_WIKILINK_{idx}__"


@dataclass(frozen=True)
class NoteLinkTarget:
    """A discoverable note under the authorized output root."""

    document_id: str
    relative_path: str
    stem: str
    link_target: str
    origins: tuple[dict[str, Any], ...]


class GraphLinker:
    """Interconecta notas atómicas insertando hipervínculos [[WikiLinks]] de Obsidian."""

    def __init__(self, output_dir: Path, *, vault_root: Path | None = None):
        self.output_dir = Path(output_dir).resolve()
        self.vault_root = (
            Path(vault_root).resolve() if vault_root is not None else self.output_dir.parent
        )

    def _vault_relative_path(self, output_relative: str) -> str:
        """Vault-relative POSIX path for a note under the authorized output root."""
        return (
            (self.output_dir / output_relative)
            .resolve()
            .relative_to(self.vault_root)
            .as_posix()
        )

    def _is_excluded(
        self, path: Path, *, include_canonical_moc: bool = False
    ) -> bool:
        """Exclude hidden/system paths and, by default, MOC/metadata notes."""
        try:
            relative = path.resolve().relative_to(self.output_dir.resolve())
        except ValueError:
            return True
        if any(part.startswith(".") for part in relative.parts):
            return True
        if _SYSTEM_DIR_NAME in relative.parts:
            return True
        if REFLOW_REVIEW_DIR_NAME in relative.parts:
            return True
        if path.name.startswith("_") and path.suffix.lower() == ".md":
            return not (
                include_canonical_moc
                and relative.as_posix() == CANONICAL_MOC_FILENAME
            )
        return False

    def enumerate_notes(self) -> list[NoteLinkTarget]:
        """Recursively list approved notes eligible for editorial graph output."""
        return self._enumerate_notes(include_all_reader_notes=False)

    def enumerate_reader_notes(self) -> list[NoteLinkTarget]:
        """List every non-system Markdown document exposed by the local reader."""
        return self._enumerate_notes(include_all_reader_notes=True)

    def _enumerate_notes(
        self, *, include_all_reader_notes: bool
    ) -> list[NoteLinkTarget]:
        if not self.output_dir.exists():
            return []

        discovered: list[tuple[str, Path, str | None, tuple[dict[str, Any], ...]]] = []
        for file_path in sorted(self.output_dir.rglob("*.md")):
            if not file_path.is_file() or self._is_excluded(
                file_path, include_canonical_moc=include_all_reader_notes
            ):
                continue
            try:
                document = MarkdownDocument.from_markdown(file_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                if not include_all_reader_notes:
                    logger.warning(
                        "Skipping invalid note during title discovery: %s",
                        file_path.name,
                    )
                    continue
                document = None
            # Los derivados editoriales sólo entran en el grafo después de
            # la aprobación humana de 4_salida. Los MOC y marcos del sistema
            # quedan excluidos arriba por su prefijo `_`.
            if (
                document is not None
                and not include_all_reader_notes
                and document.metadata.get("status") != "approved"
            ):
                continue
            relative = file_path.resolve().relative_to(self.output_dir.resolve()).as_posix()
            discovered.append(
                (
                    relative,
                    file_path,
                    document.note_id if document is not None else None,
                    (
                        tuple(origin.to_dict() for origin in document.origins)
                        if document is not None
                        else ()
                    ),
                )
            )

        stem_counts: dict[str, int] = {}
        for _, path, _note_id, _origins in discovered:
            stem_counts[path.stem] = stem_counts.get(path.stem, 0) + 1

        notes: list[NoteLinkTarget] = []
        for relative, path, note_id, origins in discovered:
            stem = path.stem
            if stem_counts[stem] > 1:
                link_target = relative[: -len(".md")] if relative.endswith(".md") else relative
            else:
                link_target = stem
            notes.append(
                NoteLinkTarget(
                    document_id=note_id
                    or document_id_for_relative_path(self._vault_relative_path(relative)),
                    relative_path=relative,
                    stem=stem,
                    link_target=link_target,
                    origins=origins,
                )
            )
        return notes

    def get_existing_note_titles(self) -> List[str]:
        """Return WikiLink targets (issue-qualified when stems collide)."""
        return [note.link_target for note in self.enumerate_notes()]

    def _normalize_relative_path(self, relative_path: str | None) -> str | None:
        if not relative_path:
            return None
        normalized = relative_path.replace("\\", "/").lstrip("./")
        return normalized

    def _current_stem(
        self,
        current_title: str,
        current_relative_path: str | None,
    ) -> str:
        if current_relative_path:
            return Path(current_relative_path).stem
        return Path(current_title).stem

    def _should_skip_note(
        self,
        note: NoteLinkTarget,
        current_title: str,
        current_relative_path: str | None,
    ) -> bool:
        # Always skip the current note's own stem — never substitute another
        # issue's namesake for self-title text under collisions.
        current_stem = self._current_stem(current_title, current_relative_path)
        if note.stem.lower() == current_stem.lower():
            return True
        if current_relative_path and note.relative_path == current_relative_path:
            return True
        return len(note.stem) < 3

    def _pick_target_for_stem(
        self,
        stem: str,
        notes: list[NoteLinkTarget],
        current_title: str,
        current_relative_path: str | None,
    ) -> Optional[NoteLinkTarget]:
        """Choose a link target for a stem; skip when still ambiguous or self."""
        current_stem = self._current_stem(current_title, current_relative_path)
        if stem.lower() == current_stem.lower():
            # Own title text must stay unlinked; do not cross-link to a namesake.
            return None

        candidates = [
            note
            for note in notes
            if note.stem.lower() == stem.lower()
            and not (
                current_relative_path and note.relative_path == current_relative_path
            )
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        if current_relative_path and "/" in current_relative_path:
            current_issue = current_relative_path.split("/", 1)[0]
            same_issue = [
                note
                for note in candidates
                if note.relative_path.startswith(f"{current_issue}/")
            ]
            if len(same_issue) == 1:
                return same_issue[0]
        return None

    def auto_link_content(
        self,
        note_content: str,
        current_title: str,
        *,
        current_relative_path: str | None = None,
        note_catalog: Sequence[NoteLinkTarget] | None = None,
    ) -> str:
        """Insert [[WikiLinks]] into the body only; never frontmatter or code."""
        notes = list(note_catalog) if note_catalog is not None else self.enumerate_notes()
        # Longer stems first so specific titles win over shorter substrings.
        unique_stems = sorted({note.stem for note in notes}, key=len, reverse=True)
        current_rel = self._normalize_relative_path(current_relative_path)

        document = MarkdownDocument.from_markdown(note_content)
        body = document.body

        code_blocks: list[str] = []

        def mask_code(match: re.Match[str]) -> str:
            code_blocks.append(match.group(0))
            return _CODE_PLACEHOLDER.format(idx=len(code_blocks) - 1)

        # Closed fences, then unclosed fence-to-EOF, then inline code.
        body = re.sub(r"```[\s\S]*?```", mask_code, body)
        body = re.sub(r"```[\s\S]*\Z", mask_code, body)
        body = re.sub(r"`[^`\n]+`", mask_code, body)

        wikilinks: list[str] = []

        def mask_wikilink(match: re.Match[str]) -> str:
            wikilinks.append(match.group(0))
            return _WIKILINK_PLACEHOLDER.format(idx=len(wikilinks) - 1)

        body = re.sub(r"\[\[[^\]]+\]\]", mask_wikilink, body)

        for stem in unique_stems:
            target_note = self._pick_target_for_stem(
                stem, notes, current_title, current_rel
            )
            if target_note is None:
                continue
            if self._should_skip_note(target_note, current_title, current_rel):
                continue

            pattern_str = r"[ _]".join(
                re.escape(part) for part in re.split(r"[ _]", stem) if part
            )
            if not pattern_str:
                continue
            pattern = re.compile(
                rf"(?<!\[\[)(?<!\[)\b({pattern_str})\b(?!\]\])(?!\])",
                re.IGNORECASE,
            )
            link_target = target_note.link_target

            def replace_with_wikilink(
                match: re.Match[str],
                *,
                target: str = link_target,
            ) -> str:
                matched_text = match.group(1)
                if matched_text == target:
                    return f"[[{target}]]"
                return f"[[{target}|{matched_text}]]"

            body = pattern.sub(replace_with_wikilink, body)

        for idx, wikilink in enumerate(wikilinks):
            body = body.replace(_WIKILINK_PLACEHOLDER.format(idx=idx), wikilink)
        for idx, code_str in enumerate(code_blocks):
            body = body.replace(_CODE_PLACEHOLDER.format(idx=idx), code_str)

        return MarkdownDocument(metadata=document.metadata, body=body).to_markdown()
