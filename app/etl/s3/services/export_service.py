# services/export_service.py

from __future__ import annotations

from typing import Any, Dict, Optional

from app.etl.s3.utils.helpers import utc_now

from app.etl.s3.utils.s3_paths import (
    audit_metadata_key,
    audit_root,
    blockchain_export_key,
    timeline_key,
)


class BlockchainExportService:
    def __init__(self, s3):
        self.s3 = s3

    def build_export_payload(
        self,
        org_id: str,
        audit_id: str,
        project_id: str = "0",
        ai_system_id: str = "0",
        *,
        org_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        meta = self.s3.read_json(
            audit_metadata_key(org_id, audit_id, project_id, ai_system_id)
        )
        timeline = self.s3.read_json(
            timeline_key(org_id, audit_id, project_id, ai_system_id)
        )
        root = audit_root(org_id, audit_id, project_id, ai_system_id)
        return {
            "exported_at": utc_now(),
            "audit_root": root,
            "metadata": meta,
            "timeline": timeline,
            "org_profile": org_profile,
        }

    def write_blockchain_export(
        self,
        audit_id: str,
        org_id: str,
        project_id: str = "0",
        ai_system_id: str = "0",
        *,
        org_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = self.build_export_payload(
            org_id,
            audit_id,
            project_id,
            ai_system_id,
            org_profile=org_profile,
        )
        self.s3.write_json(blockchain_export_key(audit_id), payload)
        return payload
