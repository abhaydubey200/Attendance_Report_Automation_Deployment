"""Application exception hierarchy."""


class AppError(Exception):
    """Base class for expected, user-reportable application errors."""


class ConfigurationError(AppError):
    """Configuration is missing, malformed or violates an environment rule."""


class DatabaseConfigurationError(ConfigurationError):
    """Database profile or credentials are incomplete."""


class AuthenticationError(AppError):
    """Login failed. Message is deliberately generic."""


class AuthorizationError(AppError):
    """The authenticated principal lacks the required permission or scope."""


class InvalidStateTransition(AppError):
    """A processing or upload state transition is not allowed."""
