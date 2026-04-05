"""
Purpose: Thin boto3 S3 wrapper used across the app — JSON get/put, bytes, copy, delete,
and list_objects_v2 (bucket and region from environment).
"""

import json
import os

import boto3


class S3Client:
    def __init__(self, bucket: str):
        self.bucket = bucket
        endpoint_url = os.getenv("AWS_ENDPOINT_URL") or None
        region = os.getenv("AWS_DEFAULT_REGION", "ap-south-1")
        self.client = boto3.client("s3", region_name=region, endpoint_url=endpoint_url)

    def read_json(self, key: str):
        try:
            res = self.client.get_object(Bucket=self.bucket, Key=key)
            return json.loads(res["Body"].read())
        except self.client.exceptions.NoSuchKey:
            return None
        except Exception:
            return None

    def write_json(self, key: str, data) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(data),
            ContentType="application/json",
        )

    def get_bytes(self, key: str) -> bytes:
        try:
            res = self.client.get_object(Bucket=self.bucket, Key=key)
            return res["Body"].read()
        except Exception:
            return b""

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    def copy_object(self, src_key: str, dest_key: str) -> None:
        self.client.copy_object(
            Bucket=self.bucket,
            CopySource={"Bucket": self.bucket, "Key": src_key},
            Key=dest_key,
        )

    def delete_object(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def list_objects_v2(self, **kwargs) -> dict:
        return self.client.list_objects_v2(**kwargs)
