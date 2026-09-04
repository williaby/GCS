"""Unit tests for GCSClient that mock out Google Cloud Storage.

These tests never touch a real bucket. They patch ``storage.Client`` so the
full client surface can be exercised in CI without credentials, which is what
the credential-gated integration tests in ``test_client.py`` cannot do.
"""

import base64
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.cloud.exceptions import GoogleCloudError, NotFound

from gcs_utilities import (
    GCSAuthError,
    GCSClient,
    GCSConfigError,
    GCSDownloadError,
    GCSNotFoundError,
    GCSUploadError,
)

GCS_ENV_VARS = (
    "GCP_SA_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GCS_BUCKET",
    "GCP_PROJECT",
)

BUCKET_NAME = "unit-test-bucket"


@pytest.fixture(autouse=True)
def isolated_gcs_env():
    """Remove GCS environment variables for the duration of each test.

    ``GCSClient._setup_credentials`` both reads and writes
    ``GOOGLE_APPLICATION_CREDENTIALS``, so tests must not leak it into
    each other.
    """
    saved = {name: os.environ.get(name) for name in GCS_ENV_VARS}
    for name in GCS_ENV_VARS:
        os.environ.pop(name, None)

    yield

    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture
def service_account_b64():
    """Return a base64-encoded, syntactically valid service account document."""
    document = {"type": "service_account", "project_id": "unit-test-project"}
    return base64.b64encode(json.dumps(document).encode("utf-8")).decode("utf-8")


@pytest.fixture
def storage_client_cls():
    """Patch ``storage.Client`` as used inside the client module."""
    with patch("gcs_utilities.client.storage.Client") as mock_cls:
        yield mock_cls


def make_bucket(name=BUCKET_NAME):
    """Build a mock bucket whose ``name`` renders as a real string."""
    bucket = MagicMock()
    bucket.name = name
    return bucket


def make_blob(name="some/blob.txt", exists=True):
    """Build a mock blob whose ``name`` renders as a real string."""
    blob = MagicMock()
    blob.name = name
    blob.exists.return_value = exists
    return blob


@pytest.fixture
def bucket():
    """Return the mock bucket wired into the ``client`` fixture."""
    return make_bucket()


@pytest.fixture
def client(service_account_b64, storage_client_cls, bucket):
    """Return a GCSClient backed by mocks, with a default bucket configured."""
    storage_client_cls.return_value.bucket.return_value = bucket
    instance = GCSClient(
        service_account_key_b64=service_account_b64,
        bucket_name=BUCKET_NAME,
    )
    yield instance
    instance.close()


class TestCredentialSetup:
    """Tests for ``GCSClient._setup_credentials``."""

    def test_missing_credentials_raise_config_error(self):
        with pytest.raises(GCSConfigError, match="No service account credentials"):
            GCSClient()

    def test_existing_adc_short_circuits_setup(self, storage_client_cls, tmp_path):
        adc_file = tmp_path / "adc.json"
        adc_file.write_text("{}", encoding="utf-8")
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc_file)

        instance = GCSClient()

        assert instance._credentials_path is None
        assert instance.bucket is None

    def test_key_from_environment_is_used(self, service_account_b64, storage_client_cls):
        os.environ["GCP_SA_KEY"] = service_account_b64

        instance = GCSClient()
        try:
            assert instance.project_id == "unit-test-project"
            assert instance._credentials_path is not None
            assert os.path.exists(instance._credentials_path)
            assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == instance._credentials_path
        finally:
            instance.close()

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not enforced on Windows")
    def test_credentials_file_is_owner_only(self, service_account_b64, storage_client_cls):
        instance = GCSClient(service_account_key_b64=service_account_b64)
        try:
            mode = os.stat(instance._credentials_path).st_mode
            assert mode & 0o777 == 0o600
        finally:
            instance.close()

    def test_explicit_project_id_wins(self, service_account_b64, storage_client_cls):
        instance = GCSClient(
            service_account_key_b64=service_account_b64,
            project_id="explicit-project",
        )
        try:
            assert instance.project_id == "explicit-project"
        finally:
            instance.close()

    def test_project_falls_back_to_env(self, storage_client_cls):
        os.environ["GCP_PROJECT"] = "env-project"
        key = base64.b64encode(json.dumps({"type": "service_account"}).encode()).decode()

        instance = GCSClient(service_account_key_b64=key)
        try:
            assert instance.project_id == "env-project"
        finally:
            instance.close()

    def test_non_base64_key_raises_auth_error(self, storage_client_cls):
        with pytest.raises(GCSAuthError, match="Invalid service account key format"):
            GCSClient(service_account_key_b64="not-base64-$$$")

    def test_non_json_key_raises_auth_error(self, storage_client_cls):
        key = base64.b64encode(b"this is not json").decode("utf-8")

        with pytest.raises(GCSAuthError, match="Invalid service account key format"):
            GCSClient(service_account_key_b64=key)

    def test_unwritable_credentials_file_raises_auth_error(
        self, service_account_b64, storage_client_cls
    ):
        with patch("gcs_utilities.client.tempfile.NamedTemporaryFile") as mock_tmp:
            mock_tmp.side_effect = OSError("disk full")

            with pytest.raises(GCSAuthError, match="Failed to setup credentials"):
                GCSClient(service_account_key_b64=service_account_b64)


class TestClientInitialisation:
    """Tests for ``GCSClient.__init__`` and bucket resolution."""

    def test_storage_client_failure_raises_auth_error(
        self, service_account_b64, storage_client_cls
    ):
        storage_client_cls.side_effect = ValueError("bad credentials")

        with pytest.raises(GCSAuthError, match="Failed to initialize GCS client"):
            GCSClient(service_account_key_b64=service_account_b64)

    def test_no_bucket_leaves_bucket_unset(self, service_account_b64, storage_client_cls):
        instance = GCSClient(service_account_key_b64=service_account_b64)
        try:
            assert instance.bucket is None
            assert instance.bucket_name is None
        finally:
            instance.close()

    def test_bucket_name_read_from_environment(
        self, service_account_b64, storage_client_cls, bucket
    ):
        os.environ["GCS_BUCKET"] = BUCKET_NAME
        storage_client_cls.return_value.bucket.return_value = bucket

        instance = GCSClient(service_account_key_b64=service_account_b64)
        try:
            assert instance.bucket_name == BUCKET_NAME
            assert instance.bucket is bucket
        finally:
            instance.close()

    def test_missing_bucket_without_auto_create_raises(
        self, service_account_b64, storage_client_cls, bucket
    ):
        bucket.exists.return_value = False
        storage_client_cls.return_value.bucket.return_value = bucket

        with pytest.raises(GCSNotFoundError, match="does not exist"):
            GCSClient(service_account_key_b64=service_account_b64, bucket_name=BUCKET_NAME)

    def test_missing_bucket_with_auto_create_creates_it(
        self, service_account_b64, storage_client_cls, bucket
    ):
        bucket.exists.return_value = False
        created = make_bucket("created-bucket")
        storage_client_cls.return_value.bucket.return_value = bucket
        storage_client_cls.return_value.create_bucket.return_value = created

        instance = GCSClient(
            service_account_key_b64=service_account_b64,
            bucket_name=BUCKET_NAME,
            auto_create_bucket=True,
        )
        try:
            storage_client_cls.return_value.create_bucket.assert_called_once_with(BUCKET_NAME)
            assert instance.bucket is created
        finally:
            instance.close()

    def test_bucket_lookup_failure_raises_auth_error(self, service_account_b64, storage_client_cls):
        storage_client_cls.return_value.bucket.side_effect = GoogleCloudError("no access")

        with pytest.raises(GCSAuthError, match="Failed to access bucket"):
            GCSClient(service_account_key_b64=service_account_b64, bucket_name=BUCKET_NAME)

    def test_set_bucket_swaps_default(self, client, storage_client_cls):
        replacement = make_bucket("second-bucket")
        storage_client_cls.return_value.bucket.return_value = replacement

        client.set_bucket("second-bucket")

        assert client.bucket_name == "second-bucket"
        assert client.bucket is replacement

    def test_get_bucket_prefers_explicit_name(self, client, storage_client_cls):
        override = make_bucket("override-bucket")
        storage_client_cls.return_value.bucket.return_value = override

        assert client._get_bucket("override-bucket") is override

    def test_get_bucket_uses_default(self, client, bucket):
        assert client._get_bucket() is bucket

    def test_get_bucket_without_any_bucket_raises(self, service_account_b64, storage_client_cls):
        instance = GCSClient(service_account_key_b64=service_account_b64)
        try:
            with pytest.raises(GCSConfigError, match="No bucket specified"):
                instance._get_bucket()
        finally:
            instance.close()


class TestPathValidation:
    """Tests for the static path-hardening helpers."""

    def test_missing_path_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Path does not exist"):
            GCSClient._validate_local_path(tmp_path / "absent.txt", must_exist=True)

    def test_unresolvable_path_raises_value_error(self, tmp_path):
        with patch.object(Path, "resolve", side_effect=OSError("loop")):
            with pytest.raises(ValueError, match="Invalid path"):
                GCSClient._validate_local_path(tmp_path / "x.txt")

    def test_existing_path_is_returned_absolute(self, tmp_path):
        target = tmp_path / "present.txt"
        target.write_text("hi", encoding="utf-8")

        resolved = GCSClient._validate_local_path(target, must_exist=True)

        assert resolved.is_absolute()


class TestUpload:
    """Tests for ``upload_file`` and ``upload_directory``."""

    def test_upload_file_returns_uri(self, client, bucket, tmp_path):
        source = tmp_path / "payload.txt"
        source.write_text("hello", encoding="utf-8")
        blob = make_blob("dest/payload.txt")
        bucket.blob.return_value = blob

        uri = client.upload_file(str(source), "/dest/payload.txt")

        assert uri == f"gs://{BUCKET_NAME}/dest/payload.txt"
        bucket.blob.assert_called_once_with("dest/payload.txt")
        blob.upload_from_filename.assert_called_once()

    def test_upload_file_attaches_metadata(self, client, bucket, tmp_path):
        source = tmp_path / "payload.txt"
        source.write_text("hello", encoding="utf-8")
        blob = make_blob()
        bucket.blob.return_value = blob

        client.upload_file(str(source), "dest/payload.txt", metadata={"owner": "unit"})

        assert blob.metadata == {"owner": "unit"}

    def test_upload_file_missing_source_raises(self, client, tmp_path):
        with pytest.raises(FileNotFoundError):
            client.upload_file(str(tmp_path / "absent.txt"), "dest/absent.txt")

    def test_upload_file_rejects_parent_traversal(self, client, tmp_path):
        source = tmp_path / "payload.txt"
        source.write_text("hello", encoding="utf-8")

        with pytest.raises(ValueError, match="cannot contain '..' segments"):
            client.upload_file(str(source), "../escape.txt")

    def test_upload_file_wraps_cloud_error(self, client, bucket, tmp_path):
        source = tmp_path / "payload.txt"
        source.write_text("hello", encoding="utf-8")
        blob = make_blob()
        blob.upload_from_filename.side_effect = GoogleCloudError("quota")
        bucket.blob.return_value = blob

        with pytest.raises(GCSUploadError, match="Failed to upload"):
            client.upload_file(str(source), "dest/payload.txt")

    def test_upload_directory_walks_tree(self, client, bucket, tmp_path):
        (tmp_path / "nested").mkdir()
        (tmp_path / "keep.txt").write_text("a", encoding="utf-8")
        (tmp_path / "nested" / "deep.txt").write_text("bb", encoding="utf-8")
        bucket.blob.return_value = make_blob()

        stats = client.upload_directory(str(tmp_path), "backup/")

        assert stats["files_uploaded"] == 2
        assert stats["total_bytes"] == 3
        assert stats["failed"] == []
        uploaded = {call.args[0] for call in bucket.blob.call_args_list}
        assert uploaded == {"backup/keep.txt", "backup/nested/deep.txt"}

    def test_upload_directory_honours_exclusions(self, client, bucket, tmp_path):
        (tmp_path / "keep.txt").write_text("a", encoding="utf-8")
        (tmp_path / "skip.log").write_text("b", encoding="utf-8")
        bucket.blob.return_value = make_blob()

        stats = client.upload_directory(str(tmp_path), "backup", exclude_patterns=["*.log"])

        assert stats["files_uploaded"] == 1
        bucket.blob.assert_called_once_with("backup/keep.txt")

    def test_upload_directory_records_failures(self, client, bucket, tmp_path):
        (tmp_path / "boom.txt").write_text("a", encoding="utf-8")
        blob = make_blob()
        blob.upload_from_filename.side_effect = GoogleCloudError("nope")
        bucket.blob.return_value = blob

        stats = client.upload_directory(str(tmp_path), "backup")

        assert stats["files_uploaded"] == 0
        assert stats["failed"] == ["boom.txt"]

    def test_upload_directory_accepts_empty_prefix(self, client, bucket, tmp_path):
        (tmp_path / "root.txt").write_text("a", encoding="utf-8")
        bucket.blob.return_value = make_blob()

        stats = client.upload_directory(str(tmp_path), "")

        assert stats["files_uploaded"] == 1
        bucket.blob.assert_called_once_with("/root.txt")


class TestDownload:
    """Tests for the download entry points."""

    def test_download_file_writes_to_disk(self, client, bucket, tmp_path):
        destination = tmp_path / "out" / "payload.txt"
        blob = make_blob()
        blob.download_to_filename.side_effect = lambda path: Path(path).write_text(
            "data", encoding="utf-8"
        )
        bucket.blob.return_value = blob

        result = client.download_file("dest/payload.txt", str(destination))

        assert Path(result).read_text(encoding="utf-8") == "data"

    def test_download_file_missing_blob_raises(self, client, bucket, tmp_path):
        bucket.blob.return_value = make_blob(exists=False)

        with pytest.raises(GCSNotFoundError, match="does not exist in GCS"):
            client.download_file("dest/absent.txt", str(tmp_path / "out.txt"))

    def test_download_file_wraps_cloud_error(self, client, bucket, tmp_path):
        blob = make_blob()
        blob.download_to_filename.side_effect = GoogleCloudError("network")
        bucket.blob.return_value = blob

        with pytest.raises(GCSDownloadError, match="Failed to download"):
            client.download_file("dest/payload.txt", str(tmp_path / "out.txt"))

    def test_download_as_bytes_returns_payload(self, client, bucket):
        blob = make_blob()
        blob.download_as_bytes.return_value = b"binary"
        bucket.blob.return_value = blob

        assert client.download_as_bytes("dest/payload.bin") == b"binary"

    def test_download_as_bytes_missing_blob_raises(self, client, bucket):
        bucket.blob.return_value = make_blob(exists=False)

        with pytest.raises(GCSNotFoundError):
            client.download_as_bytes("dest/absent.bin")

    def test_download_as_bytes_wraps_cloud_error(self, client, bucket):
        blob = make_blob()
        blob.download_as_bytes.side_effect = GoogleCloudError("network")
        bucket.blob.return_value = blob

        with pytest.raises(GCSDownloadError):
            client.download_as_bytes("dest/payload.bin")

    def test_download_as_text_returns_payload(self, client, bucket):
        blob = make_blob()
        blob.download_as_text.return_value = "text"
        bucket.blob.return_value = blob

        assert client.download_as_text("dest/payload.txt") == "text"
        blob.download_as_text.assert_called_once_with(encoding="utf-8")

    def test_download_as_text_missing_blob_raises(self, client, bucket):
        bucket.blob.return_value = make_blob(exists=False)

        with pytest.raises(GCSNotFoundError):
            client.download_as_text("dest/absent.txt")

    def test_download_as_text_wraps_decode_error(self, client, bucket):
        blob = make_blob()
        blob.download_as_text.side_effect = UnicodeDecodeError(
            "utf-8", b"\xff", 0, 1, "invalid start byte"
        )
        bucket.blob.return_value = blob

        with pytest.raises(GCSDownloadError):
            client.download_as_text("dest/payload.txt")


class TestListing:
    """Tests for ``list_files``."""

    def test_list_files_maps_blob_fields(self, client, bucket):
        blob = make_blob("dest/payload.txt")
        blob.size = 12
        blob.updated = "2026-01-01"
        blob.content_type = "text/plain"
        bucket.list_blobs.return_value = [blob]

        files = client.list_files(prefix="dest/")

        assert files == [
            {
                "name": "dest/payload.txt",
                "size": 12,
                "updated": "2026-01-01",
                "content_type": "text/plain",
                "uri": f"gs://{BUCKET_NAME}/dest/payload.txt",
            }
        ]

    def test_list_files_wraps_cloud_error(self, client, bucket):
        bucket.list_blobs.side_effect = GoogleCloudError("listing failed")

        with pytest.raises(GCSDownloadError, match="Failed to list files"):
            client.list_files()


class TestDeletion:
    """Tests for ``delete_file`` and ``delete_directory``."""

    def test_delete_file_returns_true(self, client, bucket):
        blob = make_blob()
        bucket.blob.return_value = blob

        assert client.delete_file("dest/payload.txt") is True
        blob.delete.assert_called_once_with()

    def test_delete_missing_file_ignored(self, client, bucket):
        blob = make_blob()
        blob.delete.side_effect = NotFound("gone")
        bucket.blob.return_value = blob

        assert client.delete_file("dest/absent.txt", ignore_missing=True) is False

    def test_delete_missing_file_raises(self, client, bucket):
        blob = make_blob()
        blob.delete.side_effect = NotFound("gone")
        bucket.blob.return_value = blob

        with pytest.raises(GCSNotFoundError, match="does not exist in GCS"):
            client.delete_file("dest/absent.txt")

    def test_delete_file_wraps_cloud_error(self, client, bucket):
        blob = make_blob()
        blob.delete.side_effect = GoogleCloudError("locked")
        bucket.blob.return_value = blob

        with pytest.raises(GCSDownloadError, match="Failed to delete"):
            client.delete_file("dest/payload.txt")

    def test_delete_directory_counts_successes(self, client, bucket):
        first = make_blob("dest/a.txt")
        second = make_blob("dest/b.txt")
        second.delete.side_effect = GoogleCloudError("locked")
        bucket.list_blobs.return_value = [first, second]

        assert client.delete_directory("dest/") == 1

    def test_delete_directory_accepts_empty_prefix(self, client, bucket):
        bucket.list_blobs.return_value = []

        assert client.delete_directory("") == 0
        bucket.list_blobs.assert_called_once_with(prefix="")


class TestMetadata:
    """Tests for ``file_exists`` and ``get_file_metadata``."""

    def test_file_exists_delegates_to_blob(self, client, bucket):
        bucket.blob.return_value = make_blob(exists=True)

        assert client.file_exists("dest/payload.txt") is True

    def test_get_file_metadata_returns_mapping(self, client, bucket):
        blob = make_blob("dest/payload.txt")
        blob.size = 7
        blob.content_type = "text/plain"
        blob.updated = "2026-01-02"
        blob.time_created = "2026-01-01"
        blob.md5_hash = "abc123"
        blob.metadata = {"owner": "unit"}
        bucket.blob.return_value = blob

        result = client.get_file_metadata("dest/payload.txt")

        blob.reload.assert_called_once_with()
        assert result["name"] == "dest/payload.txt"
        assert result["size"] == 7
        assert result["uri"] == f"gs://{BUCKET_NAME}/dest/payload.txt"

    def test_get_file_metadata_missing_blob_raises(self, client, bucket):
        bucket.blob.return_value = make_blob(exists=False)

        with pytest.raises(GCSNotFoundError):
            client.get_file_metadata("dest/absent.txt")


class TestLifecycle:
    """Tests for cleanup, ``close`` and context-manager behaviour."""

    def test_close_removes_credentials_file(self, service_account_b64, storage_client_cls):
        instance = GCSClient(service_account_key_b64=service_account_b64)
        credentials_path = instance._credentials_path

        instance.close()

        assert not os.path.exists(credentials_path)
        assert instance._credentials_path is None

    def test_cleanup_is_idempotent(self, service_account_b64, storage_client_cls):
        instance = GCSClient(service_account_key_b64=service_account_b64)
        instance.close()

        instance.close()

        assert instance._credentials_path is None

    def test_cleanup_tolerates_unlink_failure(self, service_account_b64, storage_client_cls):
        instance = GCSClient(service_account_key_b64=service_account_b64)
        try:
            with patch("gcs_utilities.client.os.unlink", side_effect=OSError("busy")):
                instance.close()

            assert instance._credentials_path is not None
        finally:
            with patch("gcs_utilities.client.os.unlink"):
                instance.close()

    def test_context_manager_cleans_up(self, service_account_b64, storage_client_cls):
        with GCSClient(service_account_key_b64=service_account_b64) as instance:
            credentials_path = instance._credentials_path
            assert os.path.exists(credentials_path)

        assert not os.path.exists(credentials_path)

    def test_context_manager_does_not_swallow_exceptions(
        self, service_account_b64, storage_client_cls
    ):
        def run() -> None:
            with GCSClient(service_account_key_b64=service_account_b64):
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            run()
