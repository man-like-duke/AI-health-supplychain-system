"""Application-specific exception types.

Keeping these explicit lets the API map failures to useful HTTP status
codes without leaking implementation details.
"""


class SupplyChainError(Exception):
    """Base class for application errors."""


class DataValidationError(ValueError, SupplyChainError):
    """Raised when input data fails schema or quality checks."""


class ModelNotAvailableError(SupplyChainError):
    """Raised when the stockout model artifact cannot be loaded."""


class LLMError(SupplyChainError):
    """Base class for explanation-layer errors."""


class LLMConfigurationError(LLMError):
    """Raised when the LLM provider is not configured."""


class LLMResponseError(LLMError):
    """Raised when the LLM returns an unusable response."""


class LLMServiceError(LLMError):
    """Raised when the upstream LLM call fails."""
