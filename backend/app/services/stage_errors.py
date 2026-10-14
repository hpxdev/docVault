"""Errors raised inside pipeline stages. `transient` decides whether the stage is retried."""


class StageError(Exception):
    transient = False

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TransientStageError(StageError):
    """Retried with backoff; after the last retry the stage fails with `final_code`."""

    transient = True

    def __init__(self, code: str, message: str, final_code: str | None = None) -> None:
        super().__init__(code, message)
        self.final_code = final_code or code
