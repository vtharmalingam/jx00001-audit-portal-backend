# services/s3_client.py

import boto3
import json

class S3Client:
    def __init__(self, bucket):
        self.bucket = bucket
        self.client = boto3.client("s3")

    def read_json(self, key):
        try:
            res = self.client.get_object(Bucket=self.bucket, Key=key)
            return json.loads(res["Body"].read())
        except self.client.exceptions.NoSuchKey:
            return None

    def write_json(self, key, data):
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(data),
            ContentType="application/json",
        )

    def get_bytes(self, key: str) -> bytes:
        res = self.client.get_object(Bucket=self.bucket, Key=key)
        return res["Body"].read()

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream"):
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    def copy_object(self, src_key: str, dest_key: str):
        self.client.copy_object(
            Bucket=self.bucket,
            CopySource={"Bucket": self.bucket, "Key": src_key},
            Key=dest_key,
        )

    def delete_object(self, key: str):
        self.client.delete_object(Bucket=self.bucket, Key=key)