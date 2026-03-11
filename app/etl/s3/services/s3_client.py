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
            ContentType="application/json"
        )