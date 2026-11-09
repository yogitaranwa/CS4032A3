"""Tiny storage layer: S3-compatible object storage (SeaweedFS) or a local directory.

Credentials are never read from files in the repo. boto3 picks AWS_ACCESS_KEY_ID and
AWS_SECRET_ACCESS_KEY from the environment (in Kubernetes they come from a Secret).
"""
import os
from pathlib import Path


def parse_uri(uri):
    """'s3://bucket/some/prefix' -> ('bucket', 'some/prefix')"""
    if not uri.startswith("s3://"):
        raise ValueError(f"not an s3 uri: {uri}")
    rest = uri[len("s3://"):]
    bucket, _, key = rest.partition("/")
    return bucket, key


def s3_client(endpoint=None):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint or os.environ.get("S3_ENDPOINT"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 5}),
    )


class Store:
    """Reads and writes text objects. Pass s3_endpoint to use object storage, otherwise a local dir."""

    def __init__(self, s3_endpoint=None, local_root=None):
        self.endpoint = s3_endpoint
        self.local_root = Path(local_root) if local_root else None
        self._client = s3_client(s3_endpoint) if s3_endpoint else None

    def put_text(self, bucket, key, text):
        if self._client:
            self._client.put_object(Bucket=bucket, Key=key, Body=text.encode("utf-8"))
        else:
            path = self.local_root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def get_text(self, bucket, key):
        if self._client:
            return self._client.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
        return (self.local_root / key).read_text(encoding="utf-8")

    def list_keys(self, bucket, prefix):
        if self._client:
            keys = []
            pager = self._client.get_paginator("list_objects_v2")
            for page in pager.paginate(Bucket=bucket, Prefix=prefix):
                keys += [o["Key"] for o in page.get("Contents", [])]
            return sorted(keys)
        base = self.local_root / prefix
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.local_root)) for p in base.rglob("*") if p.is_file())

    def exists(self, bucket, key):
        return key in self.list_keys(bucket, key)
