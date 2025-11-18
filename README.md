# GCS Utilities

Streamlined Google Cloud Storage utilities for easy integration across Python projects. This package simplifies GCS operations by handling authentication and providing clean interfaces for common storage tasks.

## Features

- **Simple Authentication**: Configure once with base64-encoded service account credentials in `.env`
- **Common Operations**: Upload, download, list, and delete files with minimal code
- **Directory Support**: Upload/download entire directories with structure preservation
- **Flexible Configuration**: Default bucket or specify per-operation
- **Type Hints**: Full type annotations for better IDE support
- **Error Handling**: Custom exceptions for better error management
- **Logging**: Built-in logging for operation tracking

## Installation

### From Source (Development)

```bash
git clone <repository-url>
cd GCS
pip install -e .
```

### With Development Dependencies

```bash
pip install -e ".[dev]"
```

## Quick Start

### 1. Setup Credentials

First, encode your GCP service account key to base64:

```bash
# Linux/Mac
base64 -w 0 path/to/service-account-key.json

# Windows
certutil -encode path/to/service-account-key.json encoded.txt
```

### 2. Configure Environment

Create a `.env` file in your project root:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
GCP_SA_KEY=your_base64_encoded_service_account_key_here
GCS_BUCKET=your-bucket-name
GCP_PROJECT=your-project-id  # Optional
```

### 3. Use in Your Code

```python
from dotenv import load_dotenv
from gcs_utilities import GCSClient

# Load environment variables
load_dotenv()

# Initialize client (automatically reads from .env)
client = GCSClient()

# Upload a file
client.upload_file("local/data.json", "remote/data.json")

# Download a file
client.download_file("remote/data.json", "local/downloaded.json")

# List files
files = client.list_files(prefix="remote/")
for file in files:
    print(f"{file['name']} - {file['size']} bytes")
```

## Usage Examples

### Basic File Operations

```python
from gcs_utilities import GCSClient

client = GCSClient()

# Upload with custom content type
client.upload_file(
    "data.csv",
    "datasets/data.csv",
    content_type="text/csv"
)

# Upload with metadata
client.upload_file(
    "report.pdf",
    "reports/monthly.pdf",
    metadata={"month": "2025-11", "type": "financial"}
)

# Download to specific location
client.download_file("datasets/data.csv", "local/data.csv")

# Download as bytes (in-memory)
data = client.download_as_bytes("config.json")

# Download as text
config = client.download_as_text("config.yaml")

# Check if file exists
if client.file_exists("data.csv"):
    print("File exists!")

# Get file metadata
metadata = client.get_file_metadata("data.csv")
print(f"Size: {metadata['size']} bytes")
print(f"Updated: {metadata['updated']}")

# Delete file
client.delete_file("old-data.csv")
```

### Directory Operations

```python
# Upload entire directory
stats = client.upload_directory(
    local_dir="./data",
    gcs_prefix="datasets/training",
)
print(f"Uploaded {stats['files_uploaded']} files ({stats['total_bytes']} bytes)")

# Upload with pattern filtering
stats = client.upload_directory(
    local_dir="./project",
    gcs_prefix="backup",
    pattern="**/*.py",  # Only Python files
    exclude_patterns=["**/__pycache__/**", "**/*.pyc"]
)

# Delete directory (all files with prefix)
count = client.delete_directory("old-data/")
print(f"Deleted {count} files")
```

### List and Search

```python
# List all files in bucket
all_files = client.list_files()

# List with prefix (directory-like)
data_files = client.list_files(prefix="datasets/")

# Limit results
recent = client.list_files(max_results=10)

# Directory-like listing with delimiter
folders = client.list_files(prefix="datasets/", delimiter="/")
```

### Multiple Buckets

```python
# Use different bucket for specific operations
client.upload_file("data.json", "temp/data.json", bucket_name="other-bucket")

# Change default bucket
client.set_bucket("other-bucket")
client.upload_file("data.json", "data.json")  # Uses 'other-bucket'
```

### Advanced Configuration

```python
# Initialize without .env file
client = GCSClient(
    service_account_key_b64="base64_encoded_key...",
    bucket_name="my-bucket",
    project_id="my-project"
)

# Auto-create bucket if it doesn't exist
client = GCSClient(auto_create_bucket=True)

# Use existing GOOGLE_APPLICATION_CREDENTIALS
# (Client will detect and use existing credentials)
import os
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/path/to/key.json"
client = GCSClient()
```

### Error Handling

```python
from gcs_utilities import GCSClient, GCSNotFoundError, GCSUploadError

client = GCSClient()

try:
    client.download_file("nonexistent.txt", "local.txt")
except GCSNotFoundError:
    print("File not found in GCS")

try:
    client.upload_file("missing.txt", "remote.txt")
except FileNotFoundError:
    print("Local file not found")
except GCSUploadError as e:
    print(f"Upload failed: {e}")

# Ignore missing files when deleting
client.delete_file("maybe-exists.txt", ignore_missing=True)
```

### Logging

```python
import logging
from gcs_utilities import GCSClient

# Enable detailed logging
logging.basicConfig(level=logging.INFO)

client = GCSClient()
client.upload_file("data.json", "data.json")
# Output: ✅ Uploaded data.json (1.23 MB) → gs://bucket/data.json
```

## Integration with Other Projects

This package is designed to be used as a central dependency across multiple projects:

```python
# In your other project's requirements.txt or pyproject.toml
gcs-utilities @ git+https://github.com/your-username/GCS.git

# Or for local development
# pip install -e /path/to/GCS
```

Then in your project:

```python
from gcs_utilities import GCSClient

# All your projects can now use the same streamlined interface
client = GCSClient()
client.upload_file("output.json", "results/output.json")
```

## API Reference

### GCSClient

#### Constructor

```python
GCSClient(
    service_account_key_b64: Optional[str] = None,
    bucket_name: Optional[str] = None,
    project_id: Optional[str] = None,
    auto_create_bucket: bool = False,
)
```

#### Methods

- **`upload_file(local_path, gcs_path, bucket_name=None, content_type=None, metadata=None)`**
  - Upload a single file to GCS
  - Returns: GCS URI (gs://...)

- **`upload_directory(local_dir, gcs_prefix, bucket_name=None, pattern="**/*", exclude_patterns=None)`**
  - Upload directory with structure preservation
  - Returns: Stats dict with files_uploaded, total_bytes, failed

- **`download_file(gcs_path, local_path, bucket_name=None, create_dirs=True)`**
  - Download file to local path
  - Returns: Local file path

- **`download_as_bytes(gcs_path, bucket_name=None)`**
  - Download file as bytes (in-memory)
  - Returns: bytes

- **`download_as_text(gcs_path, bucket_name=None, encoding="utf-8")`**
  - Download file as text
  - Returns: str

- **`list_files(prefix=None, bucket_name=None, max_results=None, delimiter=None)`**
  - List files in bucket
  - Returns: List of file metadata dicts

- **`delete_file(gcs_path, bucket_name=None, ignore_missing=False)`**
  - Delete a single file
  - Returns: bool (True if deleted, False if missing with ignore_missing=True)

- **`delete_directory(prefix, bucket_name=None)`**
  - Delete all files with prefix
  - Returns: Number of files deleted

- **`file_exists(gcs_path, bucket_name=None)`**
  - Check if file exists
  - Returns: bool

- **`get_file_metadata(gcs_path, bucket_name=None)`**
  - Get file metadata
  - Returns: Metadata dict

- **`set_bucket(bucket_name, auto_create=False)`**
  - Change default bucket

### Exceptions

- **`GCSError`** - Base exception
- **`GCSAuthError`** - Authentication failures
- **`GCSConfigError`** - Configuration issues
- **`GCSUploadError`** - Upload failures
- **`GCSDownloadError`** - Download failures
- **`GCSNotFoundError`** - Resource not found

## Development

### Setup Development Environment

```bash
# Clone repository
git clone <repository-url>
cd GCS

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install with dev dependencies
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
```

### Code Formatting

```bash
# Format with black
black src/

# Lint with ruff
ruff check src/

# Type check with mypy
mypy src/
```

## Security Notes

- **Never commit** your `.env` file or service account keys to version control
- Service account credentials are stored in temporary files with restrictive permissions (0o600)
- Temporary credentials files are automatically cleaned up when the client is destroyed
- Always use `.gitignore` to exclude credential files

## License

MIT License

## Contributing

Contributions welcome! Please feel free to submit pull requests or open issues.

## Acknowledgments

Built on top of the excellent [google-cloud-storage](https://github.com/googleapis/python-storage) library.
