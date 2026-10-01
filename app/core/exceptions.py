"""Domain exceptions. Each one maps to exactly one HTTP status code.

Services raise these; a single handler in main.py turns them into JSON responses,
so route handlers stay free of try/except noise.
"""


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    default_detail: str = "Internal server error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    default_detail = "Could not validate credentials"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    default_detail = "You do not have permission to perform this action"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    default_detail = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    default_detail = "Request conflicts with the current state of the resource"


class InvalidStateTransitionError(ConflictError):
    code = "invalid_state_transition"
    default_detail = "This status change is not allowed"


class UnprocessableError(AppError):
    status_code = 422
    code = "unprocessable"
    default_detail = "Request is well-formed but semantically invalid"
