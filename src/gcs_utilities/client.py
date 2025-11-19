"""Main GCS client with streamlined operations."""

import atexit
import base64
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from google.cloud import storage
from google.cloud.exceptions import GoogleCloudError, NotFound

from .exceptions import (
    GCSAuthError,
    GCSConfigError,
    GCSDownloadError,
    GCSNotFoundError,
    GCSUploadError,
)

logger = logging.getLogger(__name__)

# Constants
BYTES_PER_MB = 1024 * 1024
DEFAULT_FILE_PATTERN = "**/*"


class GCSClient:
    """Streamlined Google Cloud Storage client.

    This client simplifies GCS operations by handling authentication
    and providing clean interfaces for common operations.

    Configuration via environment variables:
        GCP_SA_KEY: Base64-encoded service account JSON
        GCS_BUCKET: Default bucket name (optional, can be specified per operation)
        GCP_PROJECT: GCP project ID (optional, extracted from service account if not provided)

    Example:
        ```python
        from gcs_utilities import GCSClient

        # Initialize with .env file
        client = GCSClient()

        # Upload a file
        client.upload_file("local/path/file.txt", "remote/path/file.txt")

        # Download a file
        client.download_file("remote/path/file.txt", "local/path/file.txt")

        # List files
        files = client.list_files(prefix="remote/path/")
        ```
    """

    def __init__(
        self,
        service_account_key_b64: str | None = None,
        bucket_name: str | None = None,
        project_id: str | None = None,
        auto_create_bucket: bool = False,
    ):
        """Initialize GCS client.

        Args:
            service_account_key_b64: Base64-encoded service account JSON.
                If not provided, reads from GCP_SA_KEY env var.
            bucket_name: Default bucket name. If not provided, reads from GCS_BUCKET env var.
            project_id: GCP project ID. If not provided, extracts from service account.
            auto_create_bucket: If True, creates bucket if it doesn't exist.

        Raises:
            GCSAuthError: If authentication fails.
            GCSConfigError: If required configuration is missing.
        """
        self._credentials_path: str | None = None
        self._cleanup_registered = False
        self.bucket_name = bucket_name or os.getenv("GCS_BUCKET")
        self.project_id = project_id

        # Setup authentication
        self._setup_credentials(service_account_key_b64)

        # Initialize GCS client
        try:
            self.client = storage.Client(project=self.project_id)
        except (GoogleCloudError, ValueError, OSError) as e:
            raise GCSAuthError(f"Failed to initialize GCS client: {e}") from e

        # Get or create bucket if specified
        if self.bucket_name:
            self.bucket = self._get_or_create_bucket(auto_create_bucket)
        else:
            self.bucket = None
            logger.warning(
                "No default bucket specified. You'll need to provide bucket_name "
                "for each operation or call set_bucket()."
            )

    def _setup_credentials(self, service_account_key_b64: str | None = None) -> None:
        """Setup GCS credentials from base64-encoded service account key.

        Args:
            service_account_key_b64: Base64-encoded service account JSON.

        Raises:
            GCSAuthError: If credentials setup fails.
            GCSConfigError: If credentials are not provided.
        """
        # Check if GOOGLE_APPLICATION_CREDENTIALS is already set
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            logger.info("Using existing GOOGLE_APPLICATION_CREDENTIALS")
            return

        # Get base64 key from parameter or environment
        b64_key = service_account_key_b64 or os.getenv("GCP_SA_KEY")

        if not b64_key:
            raise GCSConfigError(
                "No service account credentials provided. "
                "Set GCP_SA_KEY environment variable or pass service_account_key_b64 parameter."
            )

        try:
            # Decode base64 to get JSON content
            json_content = base64.b64decode(b64_key).decode("utf-8")
            sa_data = json.loads(json_content)

            # Extract project ID if not already set
            if not self.project_id:
                self.project_id = sa_data.get("project_id") or os.getenv("GCP_PROJECT")

            # Write to temporary file with secure permissions
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
                f.write(json_content)
                self._credentials_path = f.name

            # Set restrictive permissions (owner read/write only)
            os.chmod(self._credentials_path, 0o600)

            # Register cleanup handler to ensure credentials are removed
            if not self._cleanup_registered:
                atexit.register(self._cleanup_credentials)
                self._cleanup_registered = True

            # Set environment variable for google-cloud-storage library
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self._credentials_path

            logger.info(f"GCS credentials configured for project: {self.project_id}")

        except (base64.binascii.Error, json.JSONDecodeError) as e:
            raise GCSAuthError(f"Invalid service account key format: {e}") from e
        except (OSError, ValueError) as e:
            raise GCSAuthError(f"Failed to setup credentials: {e}") from e

    def _get_or_create_bucket(self, auto_create: bool = False) -> storage.Bucket:
        """Get bucket or optionally create it if it doesn't exist.

        Args:
            auto_create: If True, creates bucket if it doesn't exist.

        Returns:
            Storage bucket object.

        Raises:
            GCSNotFoundError: If bucket doesn't exist and auto_create is False.
        """
        try:
            bucket = self.client.bucket(self.bucket_name)
            # Check if bucket exists
            if not bucket.exists():
                if auto_create:
                    logger.info(f"Creating bucket: {self.bucket_name}")
                    bucket = self.client.create_bucket(self.bucket_name)
                else:
                    raise GCSNotFoundError(
                        f"Bucket '{self.bucket_name}' does not exist. "
                        "Set auto_create_bucket=True to create it automatically."
                    )
            return bucket
        except Exception as e:
            if isinstance(e, GCSNotFoundError):
                raise
            raise GCSAuthError(f"Failed to access bucket '{self.bucket_name}': {e}") from e

    def set_bucket(self, bucket_name: str, auto_create: bool = False) -> None:
        """Set or change the default bucket.

        Args:
            bucket_name: Name of the bucket.
            auto_create: If True, creates bucket if it doesn't exist.
        """
        self.bucket_name = bucket_name
        self.bucket = self._get_or_create_bucket(auto_create)

    @staticmethod
    def _validate_local_path(path: Path, must_exist: bool = False) -> Path:
        """Validate local file path for security.

        Args:
            path: Path to validate.
            must_exist: If True, raises error if path doesn't exist.

        Returns:
            Resolved absolute path.

        Raises:
            ValueError: If path is invalid or contains traversal attempts.
            FileNotFoundError: If must_exist is True and path doesn't exist.
        """
        try:
            # Resolve to absolute path to prevent traversal attacks
            resolved_path = path.resolve()

            # Check if path exists when required
            if must_exist and not resolved_path.exists():
                raise FileNotFoundError(f"Path does not exist: {path}")

            return resolved_path

        except (OSError, RuntimeError) as e:
            raise ValueError(f"Invalid path: {path} - {e}") from e

    @staticmethod
    def _sanitize_gcs_path(gcs_path: str) -> str:
        """Sanitize GCS path to prevent issues.

        Args:
            gcs_path: GCS blob path to sanitize.

        Returns:
            Sanitized path.

        Raises:
            ValueError: If path is invalid.
        """
        # Remove leading slashes (GCS paths shouldn't start with /)
        gcs_path = gcs_path.lstrip("/")

        # Check for empty path
        if not gcs_path or gcs_path.isspace():
            raise ValueError("GCS path cannot be empty")

        # Check for suspicious patterns
        if ".." in gcs_path:
            raise ValueError("GCS path cannot contain '..' segments")

        return gcs_path

    def upload_file(
        self,
        local_path: str,
        gcs_path: str,
        bucket_name: str | None = None,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Upload a single file to GCS.

        Args:
            local_path: Path to local file.
            gcs_path: Destination path in GCS (blob name).
            bucket_name: Bucket name (uses default if not specified).
            content_type: Content type for the file (auto-detected if not provided).
            metadata: Optional metadata dict to attach to the blob.

        Returns:
            Full GCS URI (gs://bucket/path).

        Raises:
            GCSUploadError: If upload fails.
            FileNotFoundError: If local file doesn't exist.
        """
        # Validate and sanitize paths
        local_file = self._validate_local_path(Path(local_path), must_exist=True)
        gcs_path = self._sanitize_gcs_path(gcs_path)

        bucket = self._get_bucket(bucket_name)
        blob = bucket.blob(gcs_path)

        try:
            # Set metadata if provided
            if metadata:
                blob.metadata = metadata

            # Upload file
            blob.upload_from_filename(str(local_file), content_type=content_type)

            full_uri = f"gs://{bucket.name}/{gcs_path}"
            file_size_mb = local_file.stat().st_size / BYTES_PER_MB

            logger.info(f"✅ Uploaded {local_path} ({file_size_mb:.2f} MB) → {full_uri}")

            return full_uri

        except GoogleCloudError as e:
            raise GCSUploadError(f"Failed to upload {local_path} to {gcs_path}: {e}") from e

    def upload_directory(
        self,
        local_dir: str,
        gcs_prefix: str,
        bucket_name: str | None = None,
        pattern: str = DEFAULT_FILE_PATTERN,
        exclude_patterns: list[str] | None = None,
    ) -> dict[str, Any]:
        """Upload a directory to GCS, preserving structure.

        Args:
            local_dir: Path to local directory.
            gcs_prefix: Prefix for GCS paths (like a directory).
            bucket_name: Bucket name (uses default if not specified).
            pattern: Glob pattern for files to include (default: all files).
            exclude_patterns: List of glob patterns to exclude.

        Returns:
            Dict with stats: {"files_uploaded": int, "total_bytes": int, "failed": list}.

        Raises:
            GCSUploadError: If upload fails.
            FileNotFoundError: If local directory doesn't exist.
        """
        # Validate local directory path
        local_path = self._validate_local_path(Path(local_dir), must_exist=True)
        gcs_prefix = self._sanitize_gcs_path(gcs_prefix) if gcs_prefix else ""

        bucket = self._get_bucket(bucket_name)

        stats = {"files_uploaded": 0, "total_bytes": 0, "failed": []}
        exclude_patterns = exclude_patterns or []

        # Get all files matching pattern
        all_files = list(local_path.glob(pattern))

        for file_path in all_files:
            if not file_path.is_file():
                continue

            # Check exclusions
            rel_path = file_path.relative_to(local_path)
            if any(rel_path.match(pattern) for pattern in exclude_patterns):
                logger.debug(f"Skipping excluded file: {rel_path}")
                continue

            # Construct GCS path
            gcs_path = f"{gcs_prefix.rstrip('/')}/{rel_path}"

            try:
                blob = bucket.blob(gcs_path)
                blob.upload_from_filename(str(file_path))

                file_size = file_path.stat().st_size
                stats["files_uploaded"] += 1
                stats["total_bytes"] += file_size

                size_mb = file_size / BYTES_PER_MB
                logger.info(f"✅ {str(rel_path):<50} ({size_mb:>6.2f} MB) → {gcs_path}")

            except GoogleCloudError as e:
                logger.error(f"❌ Failed to upload {rel_path}: {e}")
                stats["failed"].append(str(rel_path))

        total_mb = stats["total_bytes"] / BYTES_PER_MB
        logger.info(
            f"\n📦 Upload complete: {stats['files_uploaded']} files, "
            f"{total_mb:.2f} MB total"
        )

        if stats["failed"]:
            logger.warning(f"⚠️  {len(stats['failed'])} files failed to upload")

        return stats

    def download_file(
        self,
        gcs_path: str,
        local_path: str,
        bucket_name: str | None = None,
        create_dirs: bool = True,
    ) -> str:
        """Download a single file from GCS.

        Args:
            gcs_path: Path in GCS (blob name).
            local_path: Destination local path.
            bucket_name: Bucket name (uses default if not specified).
            create_dirs: If True, creates parent directories if they don't exist.

        Returns:
            Path to downloaded file.

        Raises:
            GCSDownloadError: If download fails.
            GCSNotFoundError: If file doesn't exist in GCS.
        """
        # Validate and sanitize paths
        gcs_path = self._sanitize_gcs_path(gcs_path)
        local_file = self._validate_local_path(Path(local_path), must_exist=False)

        bucket = self._get_bucket(bucket_name)
        blob = bucket.blob(gcs_path)

        # Check if blob exists
        if not blob.exists():
            raise GCSNotFoundError(f"File does not exist in GCS: gs://{bucket.name}/{gcs_path}")

        # Create parent directories if needed
        if create_dirs:
            local_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            blob.download_to_filename(str(local_file))

            file_size_mb = local_file.stat().st_size / BYTES_PER_MB
            logger.info(f"✅ Downloaded gs://{bucket.name}/{gcs_path} ({file_size_mb:.2f} MB)")

            return str(local_file)

        except GoogleCloudError as e:
            raise GCSDownloadError(
                f"Failed to download gs://{bucket.name}/{gcs_path}: {e}"
            ) from e

    def download_as_bytes(
        self,
        gcs_path: str,
        bucket_name: str | None = None,
    ) -> bytes:
        """Download a file from GCS as bytes.

        Args:
            gcs_path: Path in GCS (blob name).
            bucket_name: Bucket name (uses default if not specified).

        Returns:
            File contents as bytes.

        Raises:
            GCSDownloadError: If download fails.
            GCSNotFoundError: If file doesn't exist in GCS.
        """
        gcs_path = self._sanitize_gcs_path(gcs_path)
        bucket = self._get_bucket(bucket_name)
        blob = bucket.blob(gcs_path)

        if not blob.exists():
            raise GCSNotFoundError(f"File does not exist in GCS: gs://{bucket.name}/{gcs_path}")

        try:
            return blob.download_as_bytes()
        except GoogleCloudError as e:
            raise GCSDownloadError(
                f"Failed to download gs://{bucket.name}/{gcs_path}: {e}"
            ) from e

    def download_as_text(
        self,
        gcs_path: str,
        bucket_name: str | None = None,
        encoding: str = "utf-8",
    ) -> str:
        """Download a file from GCS as text.

        Args:
            gcs_path: Path in GCS (blob name).
            bucket_name: Bucket name (uses default if not specified).
            encoding: Text encoding (default: utf-8).

        Returns:
            File contents as string.

        Raises:
            GCSDownloadError: If download fails.
            GCSNotFoundError: If file doesn't exist in GCS.
        """
        gcs_path = self._sanitize_gcs_path(gcs_path)
        bucket = self._get_bucket(bucket_name)
        blob = bucket.blob(gcs_path)

        if not blob.exists():
            raise GCSNotFoundError(f"File does not exist in GCS: gs://{bucket.name}/{gcs_path}")

        try:
            return blob.download_as_text(encoding=encoding)
        except (GoogleCloudError, UnicodeDecodeError) as e:
            raise GCSDownloadError(
                f"Failed to download gs://{bucket.name}/{gcs_path}: {e}"
            ) from e

    def list_files(
        self,
        prefix: str | None = None,
        bucket_name: str | None = None,
        max_results: int | None = None,
        delimiter: str | None = None,
    ) -> list[dict[str, Any]]:
        """List files in GCS bucket.

        Args:
            prefix: Filter to files with this prefix.
            bucket_name: Bucket name (uses default if not specified).
            max_results: Maximum number of results to return.
            delimiter: Delimiter for directory-like listing (e.g., "/").

        Returns:
            List of dicts with file info: {"name": str, "size": int, "updated": datetime}.

        Raises:
            GCSDownloadError: If listing fails.
        """
        bucket = self._get_bucket(bucket_name)

        try:
            blobs = bucket.list_blobs(
                prefix=prefix,
                max_results=max_results,
                delimiter=delimiter,
            )

            files = []
            for blob in blobs:
                files.append({
                    "name": blob.name,
                    "size": blob.size,
                    "updated": blob.updated,
                    "content_type": blob.content_type,
                    "uri": f"gs://{bucket.name}/{blob.name}",
                })

            return files

        except GoogleCloudError as e:
            raise GCSDownloadError(f"Failed to list files: {e}") from e

    def delete_file(
        self,
        gcs_path: str,
        bucket_name: str | None = None,
        ignore_missing: bool = False,
    ) -> bool:
        """Delete a file from GCS.

        Args:
            gcs_path: Path in GCS (blob name).
            bucket_name: Bucket name (uses default if not specified).
            ignore_missing: If True, doesn't raise error if file doesn't exist.

        Returns:
            True if file was deleted, False if it didn't exist (when ignore_missing=True).

        Raises:
            GCSNotFoundError: If file doesn't exist and ignore_missing=False.
        """
        gcs_path = self._sanitize_gcs_path(gcs_path)
        bucket = self._get_bucket(bucket_name)
        blob = bucket.blob(gcs_path)

        try:
            blob.delete()
            logger.info(f"🗑️  Deleted gs://{bucket.name}/{gcs_path}")
            return True

        except NotFound:
            if ignore_missing:
                logger.debug(f"File not found (ignored): gs://{bucket.name}/{gcs_path}")
                return False
            else:
                raise GCSNotFoundError(
                    f"File does not exist in GCS: gs://{bucket.name}/{gcs_path}"
                ) from None
        except GoogleCloudError as e:
            raise GCSDownloadError(f"Failed to delete gs://{bucket.name}/{gcs_path}: {e}") from e

    def delete_directory(
        self,
        prefix: str,
        bucket_name: str | None = None,
    ) -> int:
        """Delete all files with a given prefix (directory-like deletion).

        Args:
            prefix: Prefix of files to delete.
            bucket_name: Bucket name (uses default if not specified).

        Returns:
            Number of files deleted.
        """
        prefix = self._sanitize_gcs_path(prefix) if prefix else ""
        bucket = self._get_bucket(bucket_name)

        blobs = bucket.list_blobs(prefix=prefix)
        count = 0

        for blob in blobs:
            try:
                blob.delete()
                count += 1
                logger.debug(f"🗑️  Deleted {blob.name}")
            except GoogleCloudError as e:
                logger.error(f"Failed to delete {blob.name}: {e}")

        logger.info(f"🗑️  Deleted {count} files with prefix '{prefix}'")
        return count

    def file_exists(
        self,
        gcs_path: str,
        bucket_name: str | None = None,
    ) -> bool:
        """Check if a file exists in GCS.

        Args:
            gcs_path: Path in GCS (blob name).
            bucket_name: Bucket name (uses default if not specified).

        Returns:
            True if file exists, False otherwise.
        """
        gcs_path = self._sanitize_gcs_path(gcs_path)
        bucket = self._get_bucket(bucket_name)
        blob = bucket.blob(gcs_path)
        return blob.exists()

    def get_file_metadata(
        self,
        gcs_path: str,
        bucket_name: str | None = None,
    ) -> dict[str, Any]:
        """Get metadata for a file in GCS.

        Args:
            gcs_path: Path in GCS (blob name).
            bucket_name: Bucket name (uses default if not specified).

        Returns:
            Dict with metadata including size, content_type, updated, etc.

        Raises:
            GCSNotFoundError: If file doesn't exist.
        """
        gcs_path = self._sanitize_gcs_path(gcs_path)
        bucket = self._get_bucket(bucket_name)
        blob = bucket.blob(gcs_path)

        if not blob.exists():
            raise GCSNotFoundError(f"File does not exist in GCS: gs://{bucket.name}/{gcs_path}")

        # Reload to get latest metadata
        blob.reload()

        return {
            "name": blob.name,
            "size": blob.size,
            "content_type": blob.content_type,
            "updated": blob.updated,
            "created": blob.time_created,
            "md5_hash": blob.md5_hash,
            "metadata": blob.metadata,
            "uri": f"gs://{bucket.name}/{blob.name}",
        }

    def _get_bucket(self, bucket_name: str | None = None) -> storage.Bucket:
        """Get bucket object, using default if not specified.

        Args:
            bucket_name: Optional bucket name.

        Returns:
            Storage bucket object.

        Raises:
            GCSConfigError: If no bucket is specified and no default is set.
        """
        if bucket_name:
            return self.client.bucket(bucket_name)
        elif self.bucket:
            return self.bucket
        else:
            raise GCSConfigError(
                "No bucket specified. Either set a default bucket with set_bucket() "
                "or provide bucket_name parameter."
            )

    def _cleanup_credentials(self) -> None:
        """Cleanup temporary credentials file."""
        if self._credentials_path and os.path.exists(self._credentials_path):
            try:
                os.unlink(self._credentials_path)
                logger.debug(f"Cleaned up credentials file: {self._credentials_path}")
                self._credentials_path = None
            except OSError as e:
                logger.warning(f"Failed to cleanup credentials file: {e}")

    def close(self) -> None:
        """Close the client and cleanup resources.

        This method is called automatically when using the client as a context manager.
        It can also be called manually to cleanup resources.
        """
        self._cleanup_credentials()

    def __enter__(self) -> "GCSClient":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """Context manager exit with cleanup."""
        self.close()
        return False

    def __del__(self) -> None:
        """Cleanup on deletion (fallback, not guaranteed to be called)."""
        # Note: __del__ is unreliable, but we keep it as a fallback
        # The primary cleanup is via atexit and context manager
        self._cleanup_credentials()
