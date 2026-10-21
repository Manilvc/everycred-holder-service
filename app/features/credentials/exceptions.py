"""Errors raised by the credentials feature."""

from app.core.exceptions import AppError, NotFoundError


class CredentialDocumentUnavailableError(NotFoundError):
    """Raised when the source returned no credential document."""

    error_code = "credential_document_unavailable"


class CredentialNotShareableError(AppError):
    """Raised when a credential has no public link to share."""

    error_code = "credential_not_shareable"
