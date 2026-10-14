"""AI-layer errors. All carry stable codes from MASTER_PROMPT §6."""

from app.core.errors import AppError


class AIError(AppError):
    transient = False
    status_code = 502
    code = "AI_ERROR"


class AIProviderUnavailable(AIError):
    """Timeout, rate limit (429) or 5xx from the provider. Retried with bounded backoff."""

    transient = True
    status_code = 503
    code = "AI_PROVIDER_UNAVAILABLE"


class AIRequestRejected(AIError):
    """The provider rejected the request (4xx other than 429). Not retried."""

    status_code = 502
    code = "AI_REQUEST_REJECTED"


class AIBudgetExceeded(AIError):
    status_code = 429
    code = "AI_BUDGET_EXCEEDED"


class AINotConfigured(AIError):
    status_code = 503
    code = "AI_NOT_CONFIGURED"


class AIOutputInvalid(AIError):
    """The model returned output that failed schema parsing."""

    status_code = 502
    code = "AI_OUTPUT_INVALID"
