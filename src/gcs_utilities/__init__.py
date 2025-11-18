"""GCS Utilities - Streamlined Google Cloud Storage interface."""

from .client import GCSClient
from .exceptions import GCSError, GCSAuthError, GCSUploadError, GCSDownloadError

__version__ = "0.1.0"
__all__ = ["GCSClient", "GCSError", "GCSAuthError", "GCSUploadError", "GCSDownloadError"]
