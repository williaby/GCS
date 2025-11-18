"""Custom exceptions for GCS utilities."""


class GCSError(Exception):
    """Base exception for GCS utilities."""

    pass


class GCSAuthError(GCSError):
    """Raised when authentication to GCS fails."""

    pass


class GCSUploadError(GCSError):
    """Raised when file upload to GCS fails."""

    pass


class GCSDownloadError(GCSError):
    """Raised when file download from GCS fails."""

    pass


class GCSNotFoundError(GCSError):
    """Raised when a requested GCS object is not found."""

    pass


class GCSConfigError(GCSError):
    """Raised when GCS configuration is invalid or missing."""

    pass
