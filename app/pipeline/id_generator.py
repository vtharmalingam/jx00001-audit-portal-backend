"""ID generation for the audit platform.

Organization:  ULID (26 chars, timestamp-sortable, globally unique)
Project:       Sequential 3-digit per org (001, 002, ...)
AI System:     Sequential 4-digit per project (0001, 0002, ...)
Audit ID:      Composite {org_ulid}-{project_seq}-{system_seq}
"""

from ulid import ULID

from app.etl.s3.services.s3_client import S3Client


def generate_org_id() -> str:
    """Generate a ULID-based organization ID."""
    return str(ULID()).upper()


def next_project_seq(s3: S3Client, org_id: str) -> str:
    """Return the next sequential project ID (001, 002, ...) for an org."""
    prefix = f"organizations/{org_id}/projects/"
    max_seq = 0

    token = None
    while True:
        params = {"Bucket": s3.bucket, "Prefix": prefix, "Delimiter": "/"}
        if token:
            params["ContinuationToken"] = token
        resp = s3.client.list_objects_v2(**params)

        for cp in resp.get("CommonPrefixes", []):
            folder = cp["Prefix"].rstrip("/").split("/")[-1]
            try:
                seq = int(folder)
                if seq > max_seq:
                    max_seq = seq
            except ValueError:
                continue

        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break

    return f"{max_seq + 1:03d}"


def next_system_seq(s3: S3Client, org_id: str, project_id: str) -> str:
    """Return the next sequential system ID (0001, 0002, ...) for a project."""
    prefix = f"organizations/{org_id}/projects/{project_id}/ai_systems/"
    max_seq = 0

    token = None
    while True:
        params = {"Bucket": s3.bucket, "Prefix": prefix, "Delimiter": "/"}
        if token:
            params["ContinuationToken"] = token
        resp = s3.client.list_objects_v2(**params)

        for cp in resp.get("CommonPrefixes", []):
            folder = cp["Prefix"].rstrip("/").split("/")[-1]
            try:
                seq = int(folder)
                if seq > max_seq:
                    max_seq = seq
            except ValueError:
                continue

        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break

    return f"{max_seq + 1:04d}"


def make_audit_id(org_id: str, project_id: str, system_id: str) -> str:
    """Compose an audit ID from org, project, and system IDs."""
    return f"{org_id}-{project_id}-{system_id}"
