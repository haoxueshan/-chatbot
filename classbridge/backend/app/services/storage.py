"""Private object storage; signed access is narrowly scoped and expires."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import quote

from itsdangerous import URLSafeTimedSerializer

from app.config import settings


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def signed_url(self, key: str, ttl: int = 900) -> str: ...


def delete_audio_files(asset):
    """Remove both published audio and a retained temporary file after save failure."""
    get_storage().delete(asset.storage_key)
    root=(Path(settings.data_dir)/'audio-temp').resolve()
    temporary=(root/(asset.stream_id+'.wav')).resolve()
    if temporary.is_relative_to(root):temporary.unlink(missing_ok=True)


def validate_key(key: str):
    if not key or "\\" in key or PurePosixPath(key).is_absolute() or ".." in PurePosixPath(key).parts:
        raise ValueError("无效的存储路径")
    return key


def signer():
    return URLSafeTimedSerializer(settings.secret_key, salt="classbridge-private-object-v1")


class LocalStorage:
    def __init__(self, root=None):
        self.root = Path(root or settings.data_dir).resolve() / "objects"
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key):
        path = (self.root / validate_key(key)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("存储路径越界")
        return path

    def put(self, key, data):
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)

    def read(self, key):
        return self.path(key).read_bytes()

    def delete(self, key):
        self.path(key).unlink(missing_ok=True)

    def signed_url(self, key, ttl=900):
        validate_key(key)
        token = signer().dumps({"key": key, "ttl": max(30, min(ttl, 3600))})
        return settings.public_base_url.rstrip("/") + "/api/storage/signed?token=" + quote(token)


class S3Storage:
    def __init__(self):
        import boto3
        self.client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url or None, region_name=settings.s3_region, aws_access_key_id=settings.s3_access_key_id or None, aws_secret_access_key=settings.s3_secret_access_key or None)
        self.bucket = settings.s3_bucket
        if not self.bucket:
            raise ValueError("S3_BUCKET 未配置")

    def put(self, key, data):
        self.client.put_object(Bucket=self.bucket, Key=validate_key(key), Body=data)

    def read(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=validate_key(key))["Body"].read()

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=validate_key(key))

    def signed_url(self, key, ttl=900):
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": validate_key(key)}, ExpiresIn=max(30, min(ttl, 3600)))


class OSSStorage:
    """Native OSS protocol; no assumption that an OSS endpoint implements S3."""
    def __init__(self):
        import oss2
        if not settings.oss_endpoint or not settings.oss_bucket:
            raise ValueError("OSS_ENDPOINT / OSS_BUCKET 未配置")
        if not settings.oss_endpoint.startswith("https://"):
            raise ValueError("OSS_ENDPOINT 必须使用 HTTPS")
        auth = oss2.AuthV4(settings.oss_access_key_id, settings.oss_access_key_secret)
        self.bucket = oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket, region=settings.oss_region)

    def put(self, key, data):
        self.bucket.put_object(validate_key(key), data)

    def read(self, key):
        return self.bucket.get_object(validate_key(key)).read()

    def delete(self, key):
        self.bucket.delete_object(validate_key(key))

    def signed_url(self, key, ttl=900):
        return self.bucket.sign_url("GET", validate_key(key), max(30, min(ttl, 3600)), slash_safe=True)


def get_storage() -> Storage:
    if settings.storage_backend == "oss":
        return OSSStorage()
    if settings.storage_backend == "s3":
        return S3Storage()
    if settings.storage_backend != "local":
        raise ValueError("STORAGE_BACKEND 仅支持 local、s3、oss")
    return LocalStorage()
