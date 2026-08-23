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


class CanonicalEligibilityError(ValueError):
    """Raised when a derivative does not resolve to current approved origins."""

    code = "origin_not_approved"

    def __init__(self, code: str = code) -> None:
        self.code = code
        super().__init__(code)


class OutputApprovalRequiredError(ValueError):
    """Raised when a derived output is used before editorial approval."""

    code = "output_not_approved"

    def __init__(self, document_id: str) -> None:
        self.document_id = document_id
        super().__init__(f"Output note is not approved: {document_id}")


class SharedOutputConflictError(ValueError):
    """Raised when a shared projection conflicts with an existing receipt."""

    code = "shared_output_conflict"

    def __init__(self, document_id: str) -> None:
        self.document_id = document_id
        super().__init__(f"Shared output conflict: {document_id}")


class RefinementRejectedError(ValueError):
    """Raised when a candidate lacks an accepted, current refinement verdict."""

    code = "refinement_rejected"

    def __init__(self, candidate_id: str) -> None:
        self.candidate_id = candidate_id
        super().__init__(f"Refinement candidate is not accepted: {candidate_id}")


class InvalidNoteTransitionError(ValueError):
    """Raised when a UI-controlled status transition is not allowed."""

    code = "invalid_note_transition"

    def __init__(self, document_id: str, message: str) -> None:
        self.document_id = document_id
        super().__init__(message)
