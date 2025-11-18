# GCS Utilities Examples

This directory contains example scripts demonstrating how to use the GCS Utilities package.

## Setup

Before running the examples, make sure you have:

1. **Configured your credentials** in `.env` file (see main README.md)
2. **Installed the package**:
   ```bash
   pip install -e .
   ```
3. **Installed python-dotenv** (should be included in dependencies)

## Running Examples

### Basic Usage Examples

Run all examples:

```bash
cd examples
python basic_usage.py
```

This script demonstrates:
- Uploading and downloading files
- Directory uploads
- Listing files
- File operations (exists, metadata, delete)
- Error handling
- Downloading as text/bytes

## Individual Examples

You can also run specific functions from the examples by importing them:

```python
from basic_usage import example_upload_download

example_upload_download()
```

## Creating Your Own Examples

Feel free to add your own example scripts here. The basic pattern is:

```python
from dotenv import load_dotenv
from gcs_utilities import GCSClient

# Load .env
load_dotenv()

# Initialize client
client = GCSClient()

# Use client methods
client.upload_file("local.txt", "remote.txt")
```

## Note

The examples create temporary files and upload them to your configured GCS bucket under the `examples/` prefix. They attempt to clean up after themselves, but you may want to manually verify and clean up the `examples/` prefix in your bucket after running.
