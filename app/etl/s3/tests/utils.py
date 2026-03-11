
'''
Cleanup Strategy
You MUST clean before/after tests.
'''

# tests/utils.py

def delete_prefix(s3_client, bucket, prefix):
    response = s3_client.client.list_objects_v2(
        Bucket=bucket,
        Prefix=prefix
    )

    contents = response.get("Contents", [])

    for obj in contents:
        s3_client.client.delete_object(
            Bucket=bucket,
            Key=obj["Key"]
        )