"""Storage layer with S3 and local filesystem support.

Handles JSON snapshot storage with transparent gzip compression,
switching between S3 and local filesystem based on PIPELINE_ENV.

S3 path conventions:
    raw/metagraph/{date}/{netuid}.json
    raw/registration-costs/{date}.json
    raw/hyperparameters/{date}/{netuid}.json
    raw/alpha-prices/{date}.json
    raw/tao-price/{date}.json
    derived/metrics/{date}/{netuid}.json
    derived/rankings/{date}.json
    derived/briefings/{date}.json
"""

import gzip
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from config import get_config, PipelineConfig

logger = logging.getLogger(__name__)


class StorageLayer:
    """Unified storage layer supporting S3 and local filesystem.

    Automatically switches between S3 and local filesystem based on
    the PIPELINE_ENV configuration. Supports transparent gzip compression
    for both reading and writing.
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        """Initialize storage layer.

        Args:
            config: Pipeline configuration. If None, loads from environment.
        """
        self._config = config or get_config()

        if self._config.is_aws:
            self._s3 = boto3.client("s3", region_name=self._config.region)
        else:
            self._s3 = None

    @property
    def config(self) -> PipelineConfig:
        return self._config

    # =========================================================================
    # Path Helpers
    # =========================================================================

    def get_date_path(self, prefix: str, date: str, netuid: Optional[int] = None) -> str:
        """Generate the correct storage key for a given data type.

        Args:
            prefix: Data type prefix (e.g., "raw/metagraph", "derived/metrics").
            date: ISO date string (YYYY-MM-DD).
            netuid: Optional subnet ID. If provided, appended as filename.

        Returns:
            Full storage path/key (e.g., "raw/metagraph/2024-01-15/1.json").
        """
        if netuid is not None:
            return f"{prefix}/{date}/{netuid}.json"
        return f"{prefix}/{date}.json"

    def _resolve_local_path(self, path: str) -> str:
        """Resolve a storage key to a local filesystem path."""
        return os.path.join(self._config.storage.local_output_dir, path)

    # =========================================================================
    # Core Read/Write
    # =========================================================================

    def store_snapshot(self, path: str, data: dict, compress: bool = False) -> str:
        """Store a JSON snapshot to S3 or local filesystem.

        Args:
            path: Storage key/path (e.g., "raw/metagraph/2024-01-15/1.json").
            data: Dictionary to serialize as JSON.
            compress: If True, gzip the JSON and append .gz to the path.

        Returns:
            The final storage path (may have .gz appended).
        """
        json_bytes = json.dumps(data, default=str, ensure_ascii=False).encode("utf-8")

        if compress:
            path = f"{path}.gz" if not path.endswith(".gz") else path
            content = gzip.compress(json_bytes)
            content_type = "application/gzip"
        else:
            content = json_bytes
            content_type = "application/json"

        if self._config.is_local:
            self._write_local(path, content)
        else:
            self._write_s3(path, content, content_type)

        logger.info(f"Stored snapshot: {path} ({len(content)} bytes)")
        return path

    def read_snapshot(self, path: str) -> Optional[dict]:
        """Read a JSON snapshot from S3 or local filesystem.

        Transparently handles gzip-compressed files based on .gz extension.

        Args:
            path: Storage key/path to read.

        Returns:
            Parsed dictionary, or None if the file does not exist.
        """
        if self._config.is_local:
            content = self._read_local(path)
        else:
            content = self._read_s3(path)

        if content is None:
            return None

        # Decompress if gzipped
        if path.endswith(".gz"):
            content = gzip.decompress(content)

        return json.loads(content.decode("utf-8"))

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def get_previous_day_snapshot(self, netuid: int, date: str) -> Optional[dict]:
        """Get yesterday's metagraph snapshot for a subnet.

        Args:
            netuid: Subnet ID.
            date: Current date string (YYYY-MM-DD). Yesterday is calculated from this.

        Returns:
            Parsed snapshot dict, or None if not found.
        """
        yesterday = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        path = self.get_date_path("raw/metagraph", yesterday, netuid)

        # Try uncompressed first, then compressed
        result = self.read_snapshot(path)
        if result is None:
            result = self.read_snapshot(f"{path}.gz")

        return result

    def compress_old_snapshots(self, older_than_days: int = 30) -> int:
        """Compress raw snapshot files older than N days.

        Finds uncompressed JSON files in the raw/ prefix that are older
        than the specified number of days and compresses them with gzip.

        Args:
            older_than_days: Number of days after which files should be compressed.

        Returns:
            Number of files compressed.
        """
        cutoff_date = (datetime.utcnow() - timedelta(days=older_than_days)).strftime("%Y-%m-%d")
        compressed_count = 0

        if self._config.is_local:
            compressed_count = self._compress_local_old_files("raw", cutoff_date)
        else:
            compressed_count = self._compress_s3_old_files("raw/", cutoff_date)

        logger.info(f"Compressed {compressed_count} files older than {older_than_days} days")
        return compressed_count

    def get_storage_usage_bytes(self) -> int:
        """Get total storage usage in bytes.

        Returns:
            Total size of all stored files in bytes.
        """
        if self._config.is_local:
            return self._get_local_usage()
        return self._get_s3_usage()

    # =========================================================================
    # Local Filesystem Operations
    # =========================================================================

    def _write_local(self, path: str, content: bytes) -> None:
        """Write content to local filesystem."""
        full_path = self._resolve_local_path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(content)

    def _read_local(self, path: str) -> Optional[bytes]:
        """Read content from local filesystem."""
        full_path = self._resolve_local_path(path)
        if not os.path.exists(full_path):
            return None
        with open(full_path, "rb") as f:
            return f.read()

    def _compress_local_old_files(self, prefix: str, cutoff_date: str) -> int:
        """Compress local files in prefix directory older than cutoff date."""
        compressed_count = 0
        base_dir = self._resolve_local_path(prefix)

        if not os.path.exists(base_dir):
            return 0

        for root, _dirs, files in os.walk(base_dir):
            for filename in files:
                if filename.endswith(".gz"):
                    continue
                if not filename.endswith(".json"):
                    continue

                file_path = os.path.join(root, filename)
                # Extract date from path structure (e.g., raw/metagraph/2024-01-15/1.json)
                rel_path = os.path.relpath(file_path, self._resolve_local_path(""))
                date_str = self._extract_date_from_path(rel_path)

                if date_str and date_str < cutoff_date:
                    # Read, compress, write, remove original
                    with open(file_path, "rb") as f:
                        original_content = f.read()

                    compressed_path = f"{file_path}.gz"
                    with open(compressed_path, "wb") as f:
                        f.write(gzip.compress(original_content))

                    os.remove(file_path)
                    compressed_count += 1

        return compressed_count

    def _get_local_usage(self) -> int:
        """Calculate total local storage usage in bytes."""
        total = 0
        base_dir = self._config.storage.local_output_dir

        if not os.path.exists(base_dir):
            return 0

        for root, _dirs, files in os.walk(base_dir):
            for filename in files:
                file_path = os.path.join(root, filename)
                total += os.path.getsize(file_path)

        return total

    # =========================================================================
    # S3 Operations
    # =========================================================================

    def _write_s3(self, path: str, content: bytes, content_type: str) -> None:
        """Write content to S3."""
        self._s3.put_object(
            Bucket=self._config.storage.bucket_name,
            Key=path,
            Body=content,
            ContentType=content_type,
        )

    def _read_s3(self, path: str) -> Optional[bytes]:
        """Read content from S3. Returns None if key does not exist."""
        try:
            response = self._s3.get_object(
                Bucket=self._config.storage.bucket_name,
                Key=path,
            )
            return response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise

    def _compress_s3_old_files(self, prefix: str, cutoff_date: str) -> int:
        """Compress S3 objects in prefix older than cutoff date."""
        compressed_count = 0
        bucket = self._config.storage.bucket_name
        paginator = self._s3.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]

                if key.endswith(".gz"):
                    continue
                if not key.endswith(".json"):
                    continue

                date_str = self._extract_date_from_path(key)
                if date_str and date_str < cutoff_date:
                    # Read original
                    content = self._read_s3(key)
                    if content is None:
                        continue

                    # Write compressed version
                    compressed_key = f"{key}.gz"
                    self._write_s3(compressed_key, gzip.compress(content), "application/gzip")

                    # Delete original
                    self._s3.delete_object(Bucket=bucket, Key=key)
                    compressed_count += 1

        return compressed_count

    def _get_s3_usage(self) -> int:
        """Calculate total S3 bucket usage in bytes."""
        total = 0
        bucket = self._config.storage.bucket_name
        paginator = self._s3.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                total += obj["Size"]

        return total

    # =========================================================================
    # Utilities
    # =========================================================================

    @staticmethod
    def _extract_date_from_path(path: str) -> Optional[str]:
        """Extract a YYYY-MM-DD date string from a storage path.

        Looks for path segments matching the date format.

        Args:
            path: Storage key or file path.

        Returns:
            Date string if found, None otherwise.
        """
        parts = path.replace("\\", "/").split("/")
        for part in parts:
            if len(part) == 10 and part[4] == "-" and part[7] == "-":
                try:
                    datetime.strptime(part, "%Y-%m-%d")
                    return part
                except ValueError:
                    continue
        return None
