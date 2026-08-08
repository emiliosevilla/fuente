class PathAuthorizationError(ValueError):
    """Raised when a UI-supplied path is outside its authorized Vault root."""

    code = "path_not_authorized"

    def __init__(self) -> None:
        super().__init__("Path is not authorized")


class NoteRevisionConflictError(ValueError):
    """Raised when a note mutation targets a stale revision."""

    code = "note_revision_conflict"

    def __init__(self, document_id: str) -> None:
        self.document_id = document_id
        super().__init__(f"Note revision conflict: {document_id}")


class InvalidNoteTransitionError(ValueError):
    """Raised when a UI-controlled status transition is not allowed."""

    code = "invalid_note_transition"

    def __init__(self, document_id: str, message: str) -> None:
        self.document_id = document_id
        super().__init__(message)
