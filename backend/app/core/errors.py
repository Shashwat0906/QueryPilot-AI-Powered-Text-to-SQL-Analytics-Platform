"""Error types used across the backend.

Every error that can reach the client is an `AppError`. Each has a stable
machine-readable `code`, a safe human-readable `message`, and an HTTP status.
Internal details (stack traces, file paths, credentials) are never placed in
`message`; they only go to the server log.
"""

from __future__ import annotations

from enum import Enum


class ErrorCategory(str, Enum):
    """How the retry service should treat a failure."""

    RECOVERABLE = "recoverable"  # SQL syntax / unknown column -> ask LLM to fix
    SECURITY = "security"  # forbidden statement / table -> never retried
    RESOURCE = "resource"  # timeout / too large -> not retried
    UNANSWERABLE = "unanswerable"  # model says schema can't answer it
    PROVIDER = "provider"  # LLM API failure
    INTERNAL = "internal"


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"


class LLMProviderError(AppError):
    """The LLM API could not be reached or returned something unusable."""

    status_code = 502
    code = "llm_provider_error"


class LLMResponseParseError(LLMProviderError):
    code = "llm_response_invalid"


class SQLValidationError(AppError):
    """Generated SQL failed static validation (before touching the database)."""

    status_code = 422
    code = "sql_validation_failed"

    def __init__(self, message: str, *, category: ErrorCategory, code: str | None = None):
        super().__init__(message, code=code)
        self.category = category


class QueryExecutionError(AppError):
    """The database rejected or aborted a validated query."""

    status_code = 422
    code = "query_execution_failed"

    def __init__(self, message: str, *, category: ErrorCategory, code: str | None = None):
        super().__init__(message, code=code)
        self.category = category
