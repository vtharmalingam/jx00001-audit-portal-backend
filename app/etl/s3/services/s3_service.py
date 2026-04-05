"""
Purpose: Alternate / legacy-style S3 helper (put/get bytes, object versions). Less central
than S3Client; use when versioned raw-object access is needed without the JSON-focused API.
"""

import boto3
from typing import Optional

class S3Service:
    def __init__(self, bucket_name: str, region: str = "ap-south-1"):
        self.bucket = bucket_name
        self.s3 = boto3.client("s3", region_name=region)

    def put_object(self, key: str, data: bytes, metadata: Optional[dict] = None):
        return self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            Metadata=metadata or {}
        )

    def get_object(self, key: str) -> bytes:
        response = self.s3.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def list_versions(self, key: str):
        return self.s3.list_object_versions(
            Bucket=self.bucket,
            Prefix=key
        )

    def get_object_version(self, key: str, version_id: str) -> bytes:
        response = self.s3.get_object(
            Bucket=self.bucket,
            Key=key,
            VersionId=version_id
        )
        return response["Body"].read()