class PathAuthorizationError(ValueError):
    """Raised when a UI-supplied path is outside its authorized Vault root."""

    code = "path_not_authorized"

    def __init__(self) -> None:
        super().__init__("Path is not authorized")
