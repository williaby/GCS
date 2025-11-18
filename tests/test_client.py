"""Tests for GCSClient.

Note: These tests require valid GCS credentials and will interact with real GCS buckets.
Set up a test bucket and configure credentials before running tests.
"""

import os
import tempfile
from pathlib import Path

import pytest

from gcs_utilities import GCSClient, GCSConfigError, GCSNotFoundError


class TestGCSClientInit:
    """Tests for GCSClient initialization."""

    def test_init_without_credentials_raises_error(self):
        """Test that initializing without credentials raises an error."""
        # Clear environment variables
        old_key = os.environ.pop("GCP_SA_KEY", None)
        old_creds = os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

        try:
            with pytest.raises(GCSConfigError):
                GCSClient()
        finally:
            # Restore environment variables
            if old_key:
                os.environ["GCP_SA_KEY"] = old_key
            if old_creds:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = old_creds


# Integration tests (require valid credentials)
@pytest.mark.skipif(
    not os.getenv("GCP_SA_KEY") and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
    reason="GCS credentials not configured"
)
class TestGCSClientIntegration:
    """Integration tests for GCSClient.

    These tests require valid GCS credentials and a test bucket.
    """

    @pytest.fixture
    def client(self):
        """Create a GCS client for testing."""
        return GCSClient()

    @pytest.fixture
    def test_file(self):
        """Create a temporary test file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("Test content for GCS utilities")
            temp_path = f.name

        yield temp_path

        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    def test_upload_download_file(self, client, test_file):
        """Test uploading and downloading a file."""
        gcs_path = "test/test_file.txt"

        try:
            # Upload
            uri = client.upload_file(test_file, gcs_path)
            assert uri.startswith("gs://")
            assert gcs_path in uri

            # Verify exists
            assert client.file_exists(gcs_path)

            # Download
            with tempfile.TemporaryDirectory() as tmpdir:
                download_path = os.path.join(tmpdir, "downloaded.txt")
                result = client.download_file(gcs_path, download_path)

                assert os.path.exists(result)
                with open(result, "r") as f:
                    content = f.read()
                assert content == "Test content for GCS utilities"

        finally:
            # Cleanup
            client.delete_file(gcs_path, ignore_missing=True)

    def test_download_as_text(self, client, test_file):
        """Test downloading file as text."""
        gcs_path = "test/test_text.txt"

        try:
            client.upload_file(test_file, gcs_path)
            content = client.download_as_text(gcs_path)
            assert content == "Test content for GCS utilities"

        finally:
            client.delete_file(gcs_path, ignore_missing=True)

    def test_file_not_found(self, client):
        """Test that downloading non-existent file raises error."""
        with pytest.raises(GCSNotFoundError):
            client.download_file("nonexistent/file.txt", "output.txt")

    def test_list_files(self, client, test_file):
        """Test listing files."""
        gcs_path = "test/list_test.txt"

        try:
            client.upload_file(test_file, gcs_path)

            files = client.list_files(prefix="test/")
            file_names = [f["name"] for f in files]

            assert gcs_path in file_names

        finally:
            client.delete_file(gcs_path, ignore_missing=True)

    def test_get_metadata(self, client, test_file):
        """Test getting file metadata."""
        gcs_path = "test/metadata_test.txt"

        try:
            client.upload_file(test_file, gcs_path)
            metadata = client.get_file_metadata(gcs_path)

            assert metadata["name"] == gcs_path
            assert metadata["size"] > 0
            assert "uri" in metadata
            assert metadata["uri"] == f"gs://{client.bucket_name}/{gcs_path}"

        finally:
            client.delete_file(gcs_path, ignore_missing=True)

    def test_delete_file(self, client, test_file):
        """Test deleting a file."""
        gcs_path = "test/delete_test.txt"

        client.upload_file(test_file, gcs_path)
        assert client.file_exists(gcs_path)

        deleted = client.delete_file(gcs_path)
        assert deleted is True
        assert not client.file_exists(gcs_path)

    def test_delete_missing_file_with_ignore(self, client):
        """Test deleting non-existent file with ignore_missing=True."""
        deleted = client.delete_file("nonexistent.txt", ignore_missing=True)
        assert deleted is False
