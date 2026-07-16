import logging
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from assetflow.core.logging import redact_url_tokens

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "application_error"

    def __init__(self, message: str, *, status_code: int | None = None):
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class AuthenticationError(AppError):
    status_code = 401
    code = "authentication_required"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status_code)


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error_id = str(uuid4())
    logger.exception(
        "Unhandled error %s on %s",
        error_id,
        redact_url_tokens(request.url.path),
        exc_info=exc,
    )
    return JSONResponse({"error": {"code": "internal_error", "message": "Something went wrong", "id": error_id}}, status_code=500)
