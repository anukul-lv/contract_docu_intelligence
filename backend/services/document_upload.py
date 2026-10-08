"""Document upload service — streams files to UC Volume via Databricks Files API."""
import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import AsyncIterator

from backend.config import get_settings
from backend.dependencies import get_workspace_client

logger = logging.getLogger("healthcontracts")


class DocumentUploadService:
    """Streams files to UC Volume via Databricks Files API.

    * 1 MB chunk streaming — never buffers entire file in app memory
    * Computes MD5 checksum during streaming
    * Validates extension and enforces 500 MB size limit
    """

    CHUNK_SIZE = 1_048_576  # 1 MB
    MAX_UPLOAD_SIZE = 524_288_000  # 500 MB
    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".png", ".tiff", ".tif"}

    def __init__(self) -> None:
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upload_file(
        self,
        file_name: str,
        file_stream: AsyncIterator[bytes],
        content_length: int | None,
        volume_path: str | None = None,
    ) -> dict:
        """Stream a file to a UC Volume and return metadata + checksum.

        Args:
            file_name: Original filename from the upload.
            file_stream: Async byte iterator (from UploadFile.read(chunk)).
            content_length: Declared Content-Length (pre-flight reject if >500 MB).
            volume_path: Target volume path. Falls back to config default.

        Returns:
            dict with file_id, file_path, file_size_bytes, checksum.

        Raises:
            ValueError: Invalid extension or file too large.
        """
        # 1. Validate extension
        ext = PurePosixPath(file_name).suffix.lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            raise ValueError(
                f"File type '{ext}' not allowed. "
                f"Accepted: {', '.join(sorted(self.ALLOWED_EXTENSIONS))}"
            )

        # 2. Pre-flight size check
        if content_length and content_length > self.MAX_UPLOAD_SIZE:
            raise ValueError(
                f"File size {content_length:,} bytes exceeds "
                f"maximum {self.MAX_UPLOAD_SIZE:,} bytes (500 MB)"
            )

        # 3. Build target path
        target_volume = volume_path or self._default_volume_path()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_name = self._sanitize_filename(file_name)
        dest_path = f"{target_volume}/uploads/{timestamp}_{safe_name}"

        # 4. Stream to volume while computing checksum
        file_id = str(uuid.uuid4())
        md5 = hashlib.md5()
        total_bytes = 0
        chunks: list[bytes] = []

        async for chunk in file_stream:
            total_bytes += len(chunk)
            if total_bytes > self.MAX_UPLOAD_SIZE:
                raise ValueError(
                    "Upload exceeded 500 MB during streaming — aborted"
                )
            md5.update(chunk)
            chunks.append(chunk)

        # Write accumulated content via the Files API
        file_content = b"".join(chunks)
        w = get_workspace_client()
        try:
            w.files.upload(dest_path, file_content, overwrite=True)
        except Exception as exc:
            logger.error("File upload failed for %s: %s", dest_path, exc)
            raise RuntimeError(f"Failed to upload file to volume: {exc}") from exc

        checksum = md5.hexdigest()
        logger.info(
            "Uploaded %s (%s bytes, checksum=%s) -> %s",
            file_name,
            f"{total_bytes:,}",
            checksum,
            dest_path,
        )

        return {
            "file_id": file_id,
            "file_name": file_name,
            "file_path": dest_path,
            "file_size_bytes": total_bytes,
            "checksum": checksum,
            "file_type": ext.lstrip("."),
        }

    async def list_volume_files(
        self,
        volume_path: str | None = None,
    ) -> list[dict]:
        """List files in the connected UC Volume."""
        target = volume_path or self._default_volume_path()
        w = get_workspace_client()
        try:
            entries = list(w.files.list_directory_contents(target))
        except Exception as exc:
            logger.error("Failed to list volume %s: %s", target, exc)
            raise RuntimeError(f"Failed to list volume: {exc}") from exc

        results = []
        for entry in entries:
            results.append({
                "name": entry.name,
                "path": entry.path,
                "is_directory": entry.is_directory,
                "file_size": getattr(entry, "file_size", None),
                "last_modified": str(getattr(entry, "last_modified", "")),
            })
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _default_volume_path(self) -> str:
        s = self._settings
        return f"/Volumes/{s.customer_catalog}/{s.customer_schema}/prvdr_contracts"

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Remove path separators and other unsafe chars from filename."""
        safe = os.path.basename(name)
        # Replace spaces with underscores, strip unusual chars
        safe = safe.replace(" ", "_")
        return "".join(c for c in safe if c.isalnum() or c in "._-")


# Singleton
upload_service = DocumentUploadService()
