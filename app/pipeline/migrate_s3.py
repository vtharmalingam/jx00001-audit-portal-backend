"""Migrate existing S3 data to the new nested folder structure.

Run: python -m app.pipeline.migrate_s3

What this does:
1. Re-IDs existing orgs with ULID (writes ID mapping to lookups/migration_map.json)
2. Creates project.json and system.json for each AI system
3. Restructures flat ai_systems.json into nested project/systems folders
4. Moves pipeline records into audit folders
5. Moves gap analysis results into audit folders
6. Moves review data into audit folders
7. Copies answers/feedback into the new paths
"""

import json
import logging
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

from dotenv import load_dotenv
load_dotenv()

from app.config import get_config
from app.etl.s3.services.s3_client import S3Client
from app.pipeline.id_generator import generate_org_id

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def migrate(dry_run: bool = False):
    cfg = get_config()
    s3 = S3Client(bucket=cfg.ai_assessment.s3.bucket)

    logger.info("Starting S3 migration (dry_run=%s)", dry_run)
    logger.info("Bucket: %s", s3.bucket)

    # ── Step 1: Discover existing orgs ───────────────────────────────────────
    prefix = "organizations/"
    org_ids = []
    token = None
    while True:
        params = {"Bucket": s3.bucket, "Prefix": prefix, "Delimiter": "/"}
        if token:
            params["ContinuationToken"] = token
        resp = s3.client.list_objects_v2(**params)
        for cp in resp.get("CommonPrefixes", []):
            oid = cp["Prefix"].strip("/").split("/")[-1]
            if oid:
                org_ids.append(oid)
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break

    logger.info("Found %d organizations", len(org_ids))

    # ── Step 2: Build migration map (old_id → new_ulid) ─────────────────────
    migration_map = {}
    existing_map = s3.read_json("lookups/migration_map.json") or {}

    for old_id in org_ids:
        # Skip if already a ULID (26 chars, all uppercase alphanumeric)
        if len(old_id) == 26 and old_id.isalnum() and old_id.isupper():
            logger.info("  %s — already ULID, skipping re-ID", old_id)
            migration_map[old_id] = old_id
            continue

        if old_id in existing_map:
            new_id = existing_map[old_id]
            logger.info("  %s → %s (from existing map)", old_id, new_id)
            migration_map[old_id] = new_id
            continue

        new_id = generate_org_id()
        migration_map[old_id] = new_id
        logger.info("  %s → %s (new ULID)", old_id, new_id)

    # Save migration map
    if not dry_run:
        s3.write_json("lookups/migration_map.json", {
            **migration_map,
            "_migrated_at": _now(),
        })
        logger.info("Saved migration map (%d entries)", len(migration_map))

    # ── Step 3: Migrate each org ─────────────────────────────────────────────
    for old_id, new_id in migration_map.items():
        logger.info("\n=== Migrating org: %s → %s ===", old_id, new_id)

        # 3a. Read existing org profile
        old_profile_key = f"organizations/{old_id}/org_profile.json"
        profile = s3.read_json(old_profile_key) or {}

        if not profile:
            logger.warning("  No org_profile.json found, creating minimal profile")
            profile = {"org_id": old_id, "name": old_id, "status": "pending"}

        # Update org_id in profile
        profile["org_id"] = new_id
        profile["legacy_org_id"] = old_id
        profile["migrated_at"] = _now()

        new_profile_key = f"organizations/{new_id}/org_profile.json"
        if not dry_run:
            s3.write_json(new_profile_key, profile)
        logger.info("  Wrote org_profile.json")

        # 3b. Read legacy ai_systems.json
        legacy_systems_key = f"organizations/{old_id}/ai_systems.json"
        legacy_data = s3.read_json(legacy_systems_key) or {}
        systems = legacy_data.get("systems", [])

        if not systems:
            logger.info("  No AI systems found")
            continue

        logger.info("  Found %d AI systems", len(systems))

        # Group systems by project
        project_groups = {}
        for sys in systems:
            pid = sys.get("project_id", "0") or "0"
            if pid not in project_groups:
                project_groups[pid] = []
            project_groups[pid].append(sys)

        # 3c. Create nested structure per project
        proj_seq = 0
        for old_pid, proj_systems in project_groups.items():
            proj_seq += 1
            new_pid = f"{proj_seq:03d}"

            # Write project.json
            project_doc = {
                "project_id": new_pid,
                "project_name": f"Project {new_pid}" if old_pid in ("0", "default") else old_pid,
                "org_id": new_id,
                "legacy_project_id": old_pid,
                "created_at": _now(),
            }
            proj_key = f"organizations/{new_id}/projects/{new_pid}/project.json"
            if not dry_run:
                s3.write_json(proj_key, project_doc)
            logger.info("  Project: %s → %s", old_pid, new_pid)

            # 3d. Create each AI system
            sys_seq = 0
            for sys in proj_systems:
                sys_seq += 1
                new_sid = f"{sys_seq:04d}"
                old_sid = sys.get("system_id") or sys.get("id") or str(sys_seq)
                audit_id = f"{new_id}-{new_pid}-{new_sid}"

                # Write system.json
                sys_doc = {
                    "ai_system_id": new_sid,
                    "system_id": new_sid,
                    "name": sys.get("name", old_sid),
                    "description": sys.get("description", ""),
                    "version": sys.get("version", "v1"),
                    "status": sys.get("status", "wip"),
                    "org_id": new_id,
                    "project_id": new_pid,
                    "audit_id": audit_id,
                    "manager_id": sys.get("manager_id"),
                    "manager_name": sys.get("manager_name", ""),
                    "practitioner_id": sys.get("practitioner_id"),
                    "practitioner_name": sys.get("practitioner_name", ""),
                    "legacy_system_id": old_sid,
                    "legacy_org_id": old_id,
                    "created_at": sys.get("added_at", _now()),
                }
                sys_key = f"organizations/{new_id}/projects/{new_pid}/systems/{new_sid}/system.json"
                if not dry_run:
                    s3.write_json(sys_key, sys_doc)
                logger.info("    System: %s → %s (audit: %s)", old_sid, new_sid, audit_id)

                # 3e. Migrate answers from old path to new path
                old_answers_prefix = f"organizations/{old_id}/projects/{old_pid}/systems/{old_sid}/audits/0/current/answers/"
                _copy_prefix(s3, old_answers_prefix,
                             f"organizations/{new_id}/projects/{new_pid}/systems/{new_sid}/audits/{audit_id}/current/answers/",
                             dry_run)

                # 3f. Migrate auditor_feedback
                old_feedback_prefix = f"organizations/{old_id}/projects/{old_pid}/systems/{old_sid}/audits/0/current/auditor_feedback/"
                _copy_prefix(s3, old_feedback_prefix,
                             f"organizations/{new_id}/projects/{new_pid}/systems/{new_sid}/audits/{audit_id}/current/auditor_feedback/",
                             dry_run)

                # 3g. Migrate ai_analysis
                old_ai_prefix = f"organizations/{old_id}/projects/{old_pid}/systems/{old_sid}/audits/0/current/ai_analysis/"
                _copy_prefix(s3, old_ai_prefix,
                             f"organizations/{new_id}/projects/{new_pid}/systems/{new_sid}/audits/{audit_id}/current/ai_analysis/",
                             dry_run)

                # 3h. Migrate evidence
                old_evidence_prefix = f"organizations/{old_id}/projects/{old_pid}/systems/{old_sid}/audits/0/current/evidence/"
                _copy_prefix(s3, old_evidence_prefix,
                             f"organizations/{new_id}/projects/{new_pid}/systems/{new_sid}/audits/{audit_id}/current/evidence/",
                             dry_run)

                # 3i. Migrate metadata, timeline, summary
                for fname in ("metadata.json", "timeline.json", "audit_summary.json", "progress.json", "evidence_index.json"):
                    old_key = f"organizations/{old_id}/projects/{old_pid}/systems/{old_sid}/audits/0/{fname}"
                    new_key = f"organizations/{new_id}/projects/{new_pid}/systems/{new_sid}/audits/{audit_id}/{fname}"
                    _copy_file(s3, old_key, new_key, dry_run)

        # 3j. Migrate pipeline records
        old_pipeline_key = f"pipeline/{old_id}/0/V-SYS-001/pipeline.json"
        pipeline_data = s3.read_json(old_pipeline_key)
        if pipeline_data:
            # Find matching new system
            if proj_systems:
                new_pipeline_key = f"organizations/{new_id}/projects/001/systems/0001/audits/{new_id}-001-0001/current/pipeline.json"
                pipeline_data["org_id"] = new_id
                pipeline_data["audit_id"] = f"{new_id}-001-0001"
                if not dry_run:
                    s3.write_json(new_pipeline_key, pipeline_data)
                logger.info("  Migrated pipeline record")

        # 3k. Migrate gap analysis
        old_gap_prefix = f"gap_analysis/{old_id}/"
        gap_report = s3.read_json(f"gap_analysis/{old_id}/0/V-SYS-001/gap_report.json")
        if gap_report:
            new_gap_key = f"organizations/{new_id}/projects/001/systems/0001/audits/{new_id}-001-0001/current/gap_report.json"
            gap_report["org_id"] = new_id
            if not dry_run:
                s3.write_json(new_gap_key, gap_report)
            logger.info("  Migrated gap report")

        # Migrate per-question gap results
        _copy_prefix(s3, f"gap_analysis/{old_id}/0/V-SYS-001/questions/",
                     f"organizations/{new_id}/projects/001/systems/0001/audits/{new_id}-001-0001/current/ai_analysis/",
                     dry_run)

        # 3l. Update domain lookup
        email = profile.get("email", "")
        if "@" in email:
            domain = email.split("@")[1].strip().lower()
            if not dry_run:
                s3.write_json(f"lookups/domains/{domain}.json", {"org_id": new_id, "legacy_org_id": old_id})
            logger.info("  Updated domain lookup: %s → %s", domain, new_id)

        # 3m. Update org lookup
        if not dry_run:
            s3.write_json(f"lookups/organizations/{new_id}.json", {
                "org_id": new_id, "legacy_org_id": old_id,
                "name": profile.get("name"), "email": profile.get("email"),
            })

    logger.info("\n=== Migration complete ===")
    logger.info("Orgs migrated: %d", len(migration_map))
    logger.info("Migration map saved to: lookups/migration_map.json")

    return migration_map


def _copy_prefix(s3: S3Client, old_prefix: str, new_prefix: str, dry_run: bool):
    """Copy all objects under old_prefix to new_prefix."""
    token = None
    count = 0
    while True:
        params = {"Bucket": s3.bucket, "Prefix": old_prefix}
        if token:
            params["ContinuationToken"] = token
        resp = s3.client.list_objects_v2(**params)
        for obj in resp.get("Contents", []):
            old_key = obj["Key"]
            relative = old_key[len(old_prefix):]
            new_key = new_prefix + relative
            if not dry_run:
                try:
                    s3.copy_object(old_key, new_key)
                    count += 1
                except Exception as e:
                    logger.warning("    Failed to copy %s: %s", old_key, e)
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    if count:
        logger.info("    Copied %d files from %s", count, old_prefix)


def _copy_file(s3: S3Client, old_key: str, new_key: str, dry_run: bool):
    """Copy a single file if it exists."""
    data = s3.read_json(old_key)
    if data:
        if not dry_run:
            s3.write_json(new_key, data)
        logger.info("    Copied %s", old_key.split("/")[-1])


if __name__ == "__main__":
    import sys
    dr = "--dry-run" in sys.argv
    if dr:
        logger.info("DRY RUN MODE — no writes will be made")
    migrate(dry_run=dr)
