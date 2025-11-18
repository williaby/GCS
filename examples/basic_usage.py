"""Basic usage examples for GCS Utilities.

This script demonstrates common use cases for the GCS utilities package.
Make sure to configure your .env file before running.
"""

import logging
from pathlib import Path

from dotenv import load_dotenv

from gcs_utilities import GCSClient, GCSNotFoundError

# Setup logging to see operation details
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


def example_upload_download():
    """Example: Upload and download files."""
    print("\n" + "="*60)
    print("Example 1: Upload and Download Files")
    print("="*60)

    # Load environment variables from .env
    load_dotenv()

    # Initialize client
    client = GCSClient()

    # Create a sample file
    sample_file = Path("sample_data.txt")
    sample_file.write_text("Hello from GCS Utilities!\nThis is a test file.")

    try:
        # Upload file
        uri = client.upload_file(
            str(sample_file),
            "examples/sample_data.txt",
            metadata={"source": "example_script", "version": "1.0"}
        )
        print(f"\n✅ File uploaded to: {uri}")

        # Download file
        download_path = "downloaded_sample.txt"
        client.download_file("examples/sample_data.txt", download_path)
        print(f"✅ File downloaded to: {download_path}")

        # Verify content
        downloaded_content = Path(download_path).read_text()
        print(f"\n📄 Downloaded content:\n{downloaded_content}")

        # Cleanup
        sample_file.unlink()
        Path(download_path).unlink()

    except Exception as e:
        logger.error(f"Error: {e}")


def example_directory_upload():
    """Example: Upload a directory."""
    print("\n" + "="*60)
    print("Example 2: Upload Directory")
    print("="*60)

    load_dotenv()
    client = GCSClient()

    # Create sample directory structure
    data_dir = Path("sample_data")
    data_dir.mkdir(exist_ok=True)

    (data_dir / "file1.txt").write_text("File 1 content")
    (data_dir / "file2.txt").write_text("File 2 content")

    subdir = data_dir / "subdir"
    subdir.mkdir(exist_ok=True)
    (subdir / "file3.txt").write_text("File 3 content")

    try:
        # Upload directory
        stats = client.upload_directory(
            str(data_dir),
            "examples/sample_directory"
        )

        print(f"\n📊 Upload Statistics:")
        print(f"   Files uploaded: {stats['files_uploaded']}")
        print(f"   Total bytes: {stats['total_bytes']:,}")
        print(f"   Failed: {len(stats['failed'])}")

        # Cleanup
        import shutil
        shutil.rmtree(data_dir)

    except Exception as e:
        logger.error(f"Error: {e}")


def example_list_files():
    """Example: List files in bucket."""
    print("\n" + "="*60)
    print("Example 3: List Files")
    print("="*60)

    load_dotenv()
    client = GCSClient()

    try:
        # List files with prefix
        files = client.list_files(prefix="examples/", max_results=10)

        print(f"\n📁 Found {len(files)} files:")
        for file_info in files:
            size_mb = file_info['size'] / (1024 * 1024)
            print(f"   • {file_info['name']:<50} {size_mb:>8.2f} MB")

    except Exception as e:
        logger.error(f"Error: {e}")


def example_file_operations():
    """Example: Check existence, get metadata, delete."""
    print("\n" + "="*60)
    print("Example 4: File Operations")
    print("="*60)

    load_dotenv()
    client = GCSClient()

    test_file = "examples/test_file.txt"

    try:
        # Create test file
        Path("test.txt").write_text("Test content for operations")
        client.upload_file("test.txt", test_file)

        # Check if file exists
        exists = client.file_exists(test_file)
        print(f"\n📋 File exists: {exists}")

        # Get metadata
        metadata = client.get_file_metadata(test_file)
        print(f"\n📊 File Metadata:")
        print(f"   Name: {metadata['name']}")
        print(f"   Size: {metadata['size']} bytes")
        print(f"   Content Type: {metadata['content_type']}")
        print(f"   Updated: {metadata['updated']}")
        print(f"   URI: {metadata['uri']}")

        # Delete file
        client.delete_file(test_file)
        print(f"\n🗑️  File deleted")

        # Verify deletion
        exists = client.file_exists(test_file)
        print(f"   File exists after deletion: {exists}")

        # Cleanup
        Path("test.txt").unlink()

    except Exception as e:
        logger.error(f"Error: {e}")


def example_error_handling():
    """Example: Error handling."""
    print("\n" + "="*60)
    print("Example 5: Error Handling")
    print("="*60)

    load_dotenv()
    client = GCSClient()

    # Try to download non-existent file
    try:
        client.download_file("nonexistent/file.txt", "output.txt")
    except GCSNotFoundError as e:
        print(f"\n❌ Expected error caught: {e}")

    # Delete with ignore_missing
    try:
        deleted = client.delete_file("maybe/exists.txt", ignore_missing=True)
        print(f"\n✅ Delete operation (ignore_missing=True): deleted={deleted}")
    except Exception as e:
        logger.error(f"Error: {e}")


def example_download_as_text():
    """Example: Download file as text (in-memory)."""
    print("\n" + "="*60)
    print("Example 6: Download as Text")
    print("="*60)

    load_dotenv()
    client = GCSClient()

    try:
        # Create and upload a JSON file
        import json
        config = {"app": "gcs-utilities", "version": "0.1.0", "debug": True}
        Path("config.json").write_text(json.dumps(config, indent=2))

        client.upload_file("config.json", "examples/config.json")

        # Download as text
        content = client.download_as_text("examples/config.json")
        print(f"\n📄 Downloaded content (as text):")
        print(content)

        # Parse JSON
        parsed = json.loads(content)
        print(f"\n✅ Parsed JSON: {parsed}")

        # Cleanup
        Path("config.json").unlink()
        client.delete_file("examples/config.json")

    except Exception as e:
        logger.error(f"Error: {e}")


def main():
    """Run all examples."""
    print("\n" + "🚀 GCS Utilities - Usage Examples")
    print("="*60)

    examples = [
        example_upload_download,
        example_directory_upload,
        example_list_files,
        example_file_operations,
        example_error_handling,
        example_download_as_text,
    ]

    for example in examples:
        try:
            example()
        except Exception as e:
            logger.error(f"Example failed: {e}", exc_info=True)

    print("\n" + "="*60)
    print("✅ Examples completed!")
    print("="*60)


if __name__ == "__main__":
    main()
