"""Object storage: local directory for development, S3-compatible (MinIO) in Docker."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

from api.settings import get_settings


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def ping(self) -> bool: ...


def _safe(key: str) -> str:
    if ".." in key.split("/") or key.startswith("/"):
        raise ValueError("invalid storage key")
    return key


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / _safe(key)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)  # atomic: a crash never leaves a half-written file

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        base = self._path(prefix)
        if base.is_dir():
            for p in sorted(base.rglob("*"), reverse=True):
                p.unlink() if p.is_file() else p.rmdir()
            base.rmdir()

    def ping(self) -> bool:
        return self.root.exists()


class S3Storage:
    def __init__(
        self, endpoint: str | None, bucket: str, access_key: str | None, secret_key: str | None
    ) -> None:
        import boto3

        self.bucket = bucket
        self.s3 = boto3.client(
            "s3", endpoint_url=endpoint, aws_access_key_id=access_key, aws_secret_access_key=secret_key
        )
        try:
            self.s3.head_bucket(Bucket=bucket)
        except Exception:
            self.s3.create_bucket(Bucket=bucket)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.s3.put_object(Bucket=self.bucket, Key=_safe(key), Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.bucket, Key=_safe(key))["Body"].read()

    def delete(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=_safe(key))

    def delete_prefix(self, prefix: str) -> None:
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=_safe(prefix)):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})

    def ping(self) -> bool:
        try:
            self.s3.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage == "s3":
        return S3Storage(s.s3_endpoint, s.s3_bucket, s.s3_access_key, s.s3_secret_key)
    return LocalStorage(s.storage_dir)
