import boto3

s3 = boto3.client("s3")

bucket_name = "audit-system-data-dev"

# Upload
s3.put_object(
    Bucket=bucket_name,
    Key="test/file.txt",
    Body=b"Hello from EC2 container"
)

# Read
response = s3.get_object(Bucket=bucket_name, Key="test/file.txt")
print(response["Body"].read().decode())