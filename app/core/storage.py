"""Object storage for holder files.

Holder files are profile images, DID QR codes, DID profile documents,
and verifiable presentations the wallet uploads for sharing. Only the
object key is stored in the database; URLs are built when a response
needs one.

Two backends implement :class:`ObjectStorage`:

* :class:`S3Storage` writes to a private S3 bucket and returns
  presigned URLs that expire after ``STORAGE_URL_TTL_SECONDS``. boto3 is
  synchronous, so every call runs in a worker thread.
* :class:`LocalStorage` writes under ``STORAGE_LOCAL_DIR``; the app
  serves that directory at ``/media``. Its URLs do not expire, which is
  why it is refused in production.
"""

from pathlib import Path, PurePosixPath
from typing import Annotated, Protocol

import boto3
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, StorageBackend


class InvalidObjectKeyError(ValueError):
    """Raised when an object key could escape its storage root."""


def _check_key(key: str) -> str:
    # Keys are built by the service, never taken from a request, but
    # rejecting traversal here keeps a future mistake from writing
    # outside the storage root.
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts or not key:
        raise InvalidObjectKeyError("invalid object key")
    return key


class ObjectStorage(Protocol):
    """Interface shared by the storage backends."""

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Store ``content`` under ``key``, replacing any existing object."""

    async def url_for(self, key: str) -> str:
        """Return a URL the wallet can fetch the object from."""


class LocalStorage:
    """Stores files on the local disk. Development only.

    Attributes:
        root: Directory files are written under.
        public_base_url: URL the ``root`` directory is served at.
    """

    def __init__(self, root: Path, public_base_url: str) -> None:
        self.root = root
        self.public_base_url = public_base_url.rstrip("/")

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Write ``content`` to ``root/key``."""
        target = self.root / _check_key(key)
        await run_in_threadpool(self._write, target, content)

    async def url_for(self, key: str) -> str:
        """Return the static URL of ``key``."""
        return f"{self.public_base_url}/{_check_key(key)}"

    @staticmethod
    def _write(target: Path, content: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


class S3Storage:
    """Stores files in a private S3 bucket.

    Attributes:
        bucket: Bucket name.
        prefix: Key prefix every object is written under.
        url_ttl_seconds: Lifetime of presigned URLs.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str,
        region: str,
        url_ttl_seconds: int,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.url_ttl_seconds = url_ttl_seconds
        # Credentials come from the standard AWS chain (IAM role first).
        self._client = boto3.client("s3", region_name=region)

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}/{_check_key(key)}"

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Upload ``content`` with server-side encryption."""
        await run_in_threadpool(
            self._client.put_object,
            Bucket=self.bucket,
            Key=self._full_key(key),
            Body=content,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )

    async def url_for(self, key: str) -> str:
        """Return a presigned GET URL for ``key``."""
        return await run_in_threadpool(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._full_key(key)},
            ExpiresIn=self.url_ttl_seconds,
        )


def create_storage(settings: Settings) -> ObjectStorage:
    """Build the backend selected by ``STORAGE_BACKEND``."""
    if settings.storage_backend is StorageBackend.S3:
        # The settings validator guarantees both values for S3.
        return S3Storage(
            bucket=str(settings.s3_bucket),
            prefix=settings.s3_prefix,
            region=str(settings.aws_region),
            url_ttl_seconds=settings.storage_url_ttl_seconds,
        )
    return LocalStorage(
        root=Path(settings.storage_local_dir),
        public_base_url=settings.storage_public_base_url,
    )


def get_storage(request: Request) -> ObjectStorage:
    """Return the storage created during application startup."""
    return request.state.storage


Storage = Annotated[ObjectStorage, Depends(get_storage)]
