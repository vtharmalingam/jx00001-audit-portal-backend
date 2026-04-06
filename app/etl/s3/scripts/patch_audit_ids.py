#!/usr/bin/env python3
"""Patch existing system.json files that have missing or non-ULID audit_id.

Each system.json must have a 26-char Crockford ULID in the ``audit_id`` field
so the pipeline board synthesizer (service.py line 268) can include them.

What this script does
---------------------
1. Scans all organizations/{org_id}/projects/{pid}/(ai_systems|systems)/{sid}/system.json
2. For each file with a missing or non-ULID audit_id, generates a new ULID
3. Writes the patched system.json back to S3
4. Prints a per-org/system report

Usage
-----
Dry run (no writes):
    python app/etl/s3/scripts/patch_audit_ids.py --bucket audit-system-data --dry-run

Live run:
    python app/etl/s3/scripts/patch_audit_ids.py --bucket audit-system-data

Single org:
    python app/etl/s3/scripts/patch_audit_ids.py --bucket audit-system-data --org-id <ULID>

Rebuild board/gap indexes after patching:
    python app/etl/s3/scripts/patch_audit_ids.py --bucket audit-system-data --rebuild-indexes
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, List, Optional

import boto3

_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def _is_valid_ulid(value: str) -> bool:
    if not value:
        return False
    return bool(_ULID_RE.match(str(value).strip().upper()))


def _new_ulid() -> str:
    try:
        from ulid import ULID
        return str(ULID()).upper()
    except ImportError:
        # Fallback: generate a time-ordered 26-char Crockford Base32 string
        import time
        import os
        import base64
        ts = int(time.time() * 1000)
        rand = int.from_bytes(os.urandom(10), "big")
        combined = (ts << 80) | rand
        alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
        out = []
        for _ in range(26):
            out.append(alphabet[combined & 0x1F])
            combined >>= 5
        return "".join(reversed(out))


def _list_common_prefixes(client, bucket: str, prefix: str) -> List[str]:
    """Return common prefix strings (immediate sub-folders) under a prefix."""
    out = []
    token = None
    while True:
        params = {"Bucket": bucket, "Prefix": prefix, "Delimiter": "/"}
        if token:
            params["ContinuationToken"] = token
        resp = client.list_objects_v2(**params)
        for cp in resp.get("CommonPrefixes", []):
            p = cp.get("Prefix", "")
            if p:
                out.append(p)
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    return out


def _read_json(client, bucket: str, key: str) -> Optional[dict]:
    try:
        res = client.get_object(Bucket=bucket, Key=key)
        return json.loads(res["Body"].read())
    except Exception:
        return None


def _write_json(client, bucket: str, key: str, data: dict) -> None:
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data),
        ContentType="application/json",
    )


@dataclass
class PatchResult:
    org_id: str
    project_id: str
    system_id: str
    folder: str  # "systems" or "ai_systems"
    old_audit_id: str
    new_audit_id: str
    patched: bool


@dataclass
class Stats:
    orgs_scanned: int = 0
    systems_scanned: int = 0
    already_valid: int = 0
    patched: int = 0
    skipped_no_file: int = 0
    errors: int = 0
    results: List[PatchResult] = field(default_factory=list)


def _iter_org_ids(client, bucket: str) -> List[str]:
    prefixes = _list_common_prefixes(client, bucket, "organizations/")
    out = []
    for p in prefixes:
        # "organizations/{org_id}/"
        parts = p.rstrip("/").split("/")
        if len(parts) >= 2 and parts[1]:
            out.append(parts[1])
    return sorted(out)


def patch_org(
    client,
    bucket: str,
    org_id: str,
    dry_run: bool,
    stats: Stats,
) -> None:
    stats.orgs_scanned += 1

    # List projects
    project_prefixes = _list_common_prefixes(client, bucket, f"organizations/{org_id}/projects/")
    for proj_prefix in project_prefixes:
        pid = proj_prefix.rstrip("/").split("/")[-1]
        if not pid:
            continue

        # Scan both new (systems/) and legacy (ai_systems/) folder names
        for folder in ("systems", "ai_systems"):
            sys_prefix = f"organizations/{org_id}/projects/{pid}/{folder}/"
            sys_prefixes = _list_common_prefixes(client, bucket, sys_prefix)

            for sp in sys_prefixes:
                sid = sp.rstrip("/").split("/")[-1]
                if not sid:
                    continue

                stats.systems_scanned += 1

                # Try the canonical new path first, then the folder-specific path
                key = f"organizations/{org_id}/projects/{pid}/systems/{sid}/system.json"
                doc = _read_json(client, bucket, key)
                if not doc:
                    key = f"organizations/{org_id}/projects/{pid}/{folder}/{sid}/system.json"
                    doc = _read_json(client, bucket, key)

                if not doc:
                    stats.skipped_no_file += 1
                    print(f"  [SKIP] {org_id}/{pid}/{folder}/{sid} — system.json not found")
                    continue

                old_aid = str(doc.get("audit_id") or "")

                if _is_valid_ulid(old_aid):
                    stats.already_valid += 1
                    print(f"  [OK]   {org_id}/{pid}/{folder}/{sid} — audit_id already valid ({old_aid})")
                    continue

                new_aid = _new_ulid()
                result = PatchResult(
                    org_id=org_id,
                    project_id=pid,
                    system_id=sid,
                    folder=folder,
                    old_audit_id=old_aid,
                    new_audit_id=new_aid,
                    patched=not dry_run,
                )
                stats.results.append(result)

                if dry_run:
                    print(f"  [DRY]  {org_id}/{pid}/{folder}/{sid} — would patch audit_id: {old_aid!r} → {new_aid}")
                else:
                    try:
                        doc["audit_id"] = new_aid
                        doc["audit_id_patched_at"] = datetime.now(timezone.utc).isoformat()
                        _write_json(client, bucket, key, doc)
                        stats.patched += 1
                        print(f"  [DONE] {org_id}/{pid}/{folder}/{sid} — audit_id patched: {old_aid!r} → {new_aid}")
                    except Exception as e:
                        stats.errors += 1
                        print(f"  [ERR]  {org_id}/{pid}/{folder}/{sid} — {e}")


def rebuild_indexes(bucket: str) -> None:
    """Rebuild pipeline board and organization indexes after patching."""
    print("\nRebuilding S3 indexes…")
    try:
        import boto3 as _boto3
        from app.config import get_config
        from app.etl.s3.services.s3_client import S3Client
        from app.etl.s3.services.operational_service import OperationalService
        from app.pipeline.service import PipelineService

        cfg = get_config()
        s3 = S3Client(bucket=cfg.ai_assessment.s3.bucket)
        op_svc = OperationalService(s3)
        pipe_svc = PipelineService(s3)

        # Refresh org index by re-reading all org profiles
        all_orgs = op_svc.get_all_organizations(include_system_counts=False)
        print(f"  Org index: {len(all_orgs)} orgs refreshed")

        # Board index is built lazily on next board request — no explicit rebuild needed
        # but we can clear the stale index so it rebuilds from scratch next request
        stale_key = "indexes/pipeline_board_index.json"
        try:
            s3.write_json(stale_key, {"items": [], "last_updated": datetime.now(timezone.utc).isoformat(), "_note": "cleared by patch_audit_ids.py — will rebuild on next board request"})
            print(f"  Board index cleared (will auto-rebuild on next /pipeline/board request)")
        except Exception as e:
            print(f"  Board index clear failed: {e}")

    except Exception as e:
        print(f"  Index rebuild failed: {e}")
        print("  Run the backfill scripts manually if needed.")


def run(
    bucket: str,
    org_id: Optional[str],
    dry_run: bool,
    rebuild: bool,
) -> Stats:
    client = boto3.client("s3")
    stats = Stats()

    orgs = [org_id] if org_id else _iter_org_ids(client, bucket)
    print(f"{'[DRY RUN] ' if dry_run else ''}Scanning {len(orgs)} org(s) in bucket: {bucket}\n")

    for oid in orgs:
        print(f"Org: {oid}")
        try:
            patch_org(client, bucket, oid, dry_run, stats)
        except Exception as e:
            stats.errors += 1
            print(f"  [ERR] org {oid}: {e}")

    if rebuild and not dry_run:
        rebuild_indexes(bucket)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch missing/invalid audit_id in system.json files")
    parser.add_argument("--bucket", required=True, help="S3 bucket name (e.g. audit-system-data)")
    parser.add_argument("--org-id", default=None, help="Patch a single org only")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing to S3")
    parser.add_argument("--rebuild-indexes", action="store_true", help="Clear stale board index after patching")
    args = parser.parse_args()

    stats = run(
        bucket=args.bucket,
        org_id=args.org_id,
        dry_run=args.dry_run,
        rebuild=args.rebuild_indexes,
    )

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Orgs scanned      : {stats.orgs_scanned}")
    print(f"  Systems scanned   : {stats.systems_scanned}")
    print(f"  Already valid     : {stats.already_valid}")
    print(f"  Patched           : {stats.patched}")
    print(f"  Skipped (no file) : {stats.skipped_no_file}")
    print(f"  Errors            : {stats.errors}")

    if stats.results:
        print(f"\nPatched systems ({len(stats.results)}):")
        for r in stats.results:
            status = "DRY" if not r.patched else "DONE"
            print(f"  [{status}] {r.org_id}/{r.project_id}/{r.folder}/{r.system_id}")
            print(f"        old: {r.old_audit_id!r}")
            print(f"        new: {r.new_audit_id}")

    return 1 if stats.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
