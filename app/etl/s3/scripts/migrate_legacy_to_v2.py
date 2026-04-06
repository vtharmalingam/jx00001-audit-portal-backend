#!/usr/bin/env python3
"""Migrate legacy audit S3 layout to v2 nested layout.

Legacy source (fixed ids):
  organizations/{org_id}/audits/0/

Target (fixed ids, current v2 segment name):
  organizations/{org_id}/projects/0/systems/0/audits/0/

Also ensures:
- organizations/{org_id}/projects/0/project.json
- organizations/{org_id}/projects/0/systems/0/system.json
- metadata.json includes project_id/ai_system_id when present
- purges legacy source keys after successful copy verification (default)


Dry run all orgs:
python app/etl/s3/scripts/migrate_legacy_to_v2.py --bucket <your-bucket> --dry-run

Migrate one org:
python app/etl/s3/scripts/migrate_legacy_to_v2.py --bucket <your-bucket> --org-id <org_id>

Migrate all orgs:
python app/etl/s3/scripts/migrate_legacy_to_v2.py --bucket <your-bucket>

Force overwrite existing target keys:
add --overwrite

Keep legacy source (skip purge):
add --no-purge-legacy

"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

import boto3

LEGACY_AUDIT_ID = "0"
# Target v2 scope for migrated keys (3-digit project, 4-digit system per README-datastruct).
PROJECT_ID = "001"
AI_SYSTEM_ID = "0001"


@dataclass
class MigrationStats:
    orgs_seen: int = 0
    orgs_migrated: int = 0
    keys_copied: int = 0
    keys_skipped_existing: int = 0
    metadata_patched: int = 0
    project_docs_created: int = 0
    system_docs_created: int = 0
    orgs_purged: int = 0
    keys_deleted: int = 0


def _list_objects(client, bucket: str, prefix: str) -> Iterable[str]:
    token = None
    while True:
        params = {"Bucket": bucket, "Prefix": prefix}
        if token:
            params["ContinuationToken"] = token
        resp = client.list_objects_v2(**params)
        for row in resp.get("Contents", []):
            key = row.get("Key")
            if key:
                yield key
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break


def _iter_org_ids(client, bucket: str) -> List[str]:
    prefix = "organizations/"
    token = None
    out: List[str] = []
    seen = set()
    while True:
        params = {
            "Bucket": bucket,
            "Prefix": prefix,
            "Delimiter": "/",
        }
        if token:
            params["ContinuationToken"] = token
        resp = client.list_objects_v2(**params)
        for cp in resp.get("CommonPrefixes", []):
            p = cp.get("Prefix", "").strip("/")
            parts = p.split("/")
            if len(parts) >= 2 and parts[1] and parts[1] not in seen:
                seen.add(parts[1])
                out.append(parts[1])
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    out.sort()
    return out


def _exists(client, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _read_json(client, bucket: str, key: str) -> Optional[dict]:
    try:
        res = client.get_object(Bucket=bucket, Key=key)
        return json.loads(res["Body"].read())
    except Exception:
        return None


def _write_json(client, bucket: str, key: str, data: dict, dry_run: bool) -> None:
    if dry_run:
        return
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data),
        ContentType="application/json",
    )


def _copy_key(client, bucket: str, src_key: str, dst_key: str, dry_run: bool) -> None:
    if dry_run:
        return
    client.copy_object(
        Bucket=bucket,
        CopySource={"Bucket": bucket, "Key": src_key},
        Key=dst_key,
    )


def _delete_key(client, bucket: str, key: str, dry_run: bool) -> None:
    if dry_run:
        return
    client.delete_object(Bucket=bucket, Key=key)


def migrate_org(
    client,
    bucket: str,
    org_id: str,
    dry_run: bool,
    overwrite: bool,
    purge_legacy: bool,
    stats: MigrationStats,
) -> None:
    legacy_root = f"organizations/{org_id}/audits/{LEGACY_AUDIT_ID}/"
    target_root = (
        f"organizations/{org_id}/projects/{PROJECT_ID}/"
        f"systems/{AI_SYSTEM_ID}/audits/{LEGACY_AUDIT_ID}/"
    )

    legacy_keys = list(_list_objects(client, bucket, legacy_root))
    if not legacy_keys:
        return

    stats.orgs_migrated += 1

    project_key = f"organizations/{org_id}/projects/{PROJECT_ID}/project.json"
    if overwrite or not _exists(client, bucket, project_key):
        _write_json(
            client,
            bucket,
            project_key,
            {
                "project_id": PROJECT_ID,
                "project_name": "Legacy Migration Project",
                "org_id": org_id,
                "created_at": datetime.utcnow().isoformat(),
            },
            dry_run,
        )
        stats.project_docs_created += 1

    system_key = f"organizations/{org_id}/projects/{PROJECT_ID}/systems/{AI_SYSTEM_ID}/system.json"
    if overwrite or not _exists(client, bucket, system_key):
        _write_json(
            client,
            bucket,
            system_key,
            {
                "ai_system_id": AI_SYSTEM_ID,
                "name": "Legacy Migrated AI System",
                "description": "Auto-created during legacy S3 migration",
                "version": "v1",
                "org_id": org_id,
                "project_id": PROJECT_ID,
                "created_at": datetime.utcnow().isoformat(),
            },
            dry_run,
        )
        stats.system_docs_created += 1

    for src in legacy_keys:
        relative = src[len(legacy_root) :]
        dst = f"{target_root}{relative}"

        if not overwrite and _exists(client, bucket, dst):
            stats.keys_skipped_existing += 1
            continue

        _copy_key(client, bucket, src, dst, dry_run)
        stats.keys_copied += 1

    dst_meta_key = f"{target_root}metadata.json"
    meta = _read_json(client, bucket, dst_meta_key)
    if isinstance(meta, dict):
        changed = False
        if meta.get("project_id") != PROJECT_ID:
            meta["project_id"] = PROJECT_ID
            changed = True
        if meta.get("ai_system_id") != AI_SYSTEM_ID:
            meta["ai_system_id"] = AI_SYSTEM_ID
            changed = True
        if changed:
            _write_json(client, bucket, dst_meta_key, meta, dry_run)
            stats.metadata_patched += 1

    if purge_legacy and not dry_run:
        # Safety check: only purge after every legacy key is present at destination.
        for src in legacy_keys:
            relative = src[len(legacy_root) :]
            dst = f"{target_root}{relative}"
            if not _exists(client, bucket, dst):
                raise RuntimeError(
                    f"Refusing purge for org={org_id}. Missing migrated key: {dst}"
                )

        for src in legacy_keys:
            _delete_key(client, bucket, src, dry_run=False)
            stats.keys_deleted += 1
        stats.orgs_purged += 1


def run(
    bucket: str,
    org_id: Optional[str],
    dry_run: bool,
    overwrite: bool,
    purge_legacy: bool,
) -> MigrationStats:
    client = boto3.client("s3")
    stats = MigrationStats()

    orgs = [org_id] if org_id else _iter_org_ids(client, bucket)
    stats.orgs_seen = len(orgs)

    for oid in orgs:
        migrate_org(client, bucket, oid, dry_run, overwrite, purge_legacy, stats)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy audit S3 layout into v2 nested layout")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--org-id", default=None, help="Migrate one org only")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, no writes")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite target keys if they exist")
    parser.add_argument(
        "--no-purge-legacy",
        action="store_true",
        help="Keep legacy organizations/{org_id}/audits/0/ keys after migration",
    )
    args = parser.parse_args()

    stats = run(
        bucket=args.bucket,
        org_id=args.org_id,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        purge_legacy=not args.no_purge_legacy,
    )

    print("Migration complete")
    print(json.dumps(stats.__dict__, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
