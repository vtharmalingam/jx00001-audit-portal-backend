#!/usr/bin/env python3
"""Load synthetic org / project / system / audit / answers into S3 for integration testing.

Uses the v2 layout (README-datastruct.md): ULID org & audit, 3-digit project, 4-digit system.

Examples (from repository root, with AWS creds and bucket configured)::

    python app/etl/s3/scripts/seed_synthetic_bucket.py
    python app/etl/s3/scripts/seed_synthetic_bucket.py --bucket my-audit-bucket
    python app/etl/s3/scripts/seed_synthetic_bucket.py --prefix dev/synthetic/ --output seed-output.json
    python app/etl/s3/scripts/seed_synthetic_bucket.py --firm-demo

Firm demo (``--firm-demo``): org with ``riskfirm.com`` domain + systems ``0001`` (full audit seed) and
``0002``/``0003`` (metadata + audits only). Matches ``AuthUserService`` demo logins
``firm.admin@riskfirm.com``, ``firm.manager@riskfirm.com``, ``firm.practitioner@riskfirm.com``.

Environment:
    AWS credentials and region as usual for boto3. Optional: ``AWS_ENDPOINT_URL`` for LocalStack.
    Bucket defaults to ``ai_assessment.s3.bucket`` in ``app/config.yaml`` unless ``--bucket`` is set.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

_MANIFEST_PATH = Path(__file__).resolve().parent / "seed_data" / "synthetic_manifest.json"
_FIRM_DEMO_MANIFEST = Path(__file__).resolve().parent / "seed_data" / "firm_demo_manifest.json"


def _load_manifest(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def run_seed(
    s3,
    manifest: Dict[str, Any],
    *,
    write_gap_index: bool = True,
    write_review_stub: bool = True,
) -> Dict[str, Any]:
    from app.etl.s3.services.answer_service import AnswerService
    from app.etl.s3.services.audit_lifecycle_service import AuditLifecycleService
    from app.etl.s3.services.auditor_service import AuditorService
    from app.etl.s3.services.current_index import sync_ai_analysis_index
    from app.etl.s3.services.operational_service import OperationalService
    from app.etl.s3.services.review_service import ReviewService
    from app.etl.s3.utils.helpers import utc_now
    from app.etl.s3.utils.s3_paths import ai_key
    from app.pipeline.models import GapAnalysisStatus, PipelineStage
    from app.pipeline.router import GAP_REPORTS_INDEX_KEY, _update_gap_index
    from app.pipeline.service import PipelineService

    ops = OperationalService(s3)
    org_cfg = manifest["organization"]
    proj_cfg = manifest["project"]
    sys_cfg = manifest["ai_system"]

    org = ops.create_org(
        org_cfg["name"],
        org_cfg["email"],
        status=org_cfg.get("status", "pending"),
        stage=org_cfg.get("stage", "not_started"),
        aict_approved=org_cfg.get("aict_approved", False),
        onboarded_by_type=org_cfg.get("onboarded_by_type", ""),
        domains=org_cfg.get("domains", []),
    )
    org_id = org["org_id"]

    ops.create_project(org_id, proj_cfg["project_name"], project_id=proj_cfg["project_id"])
    project_id = proj_cfg["project_id"]

    system_body = {
        "project_id": project_id,
        "project_name": proj_cfg["project_name"],
        "system_id": sys_cfg["system_id"],
        "name": sys_cfg.get("name", sys_cfg["system_id"]),
        "description": sys_cfg.get("description", ""),
        "version": sys_cfg.get("version", "v1"),
        "status": sys_cfg.get("status", "in_progress"),
    }
    sys_doc = ops.add_ai_system(org_id, system_body)
    ai_system_id = str(sys_doc.get("system_id") or sys_cfg["system_id"])
    audit_id = str(sys_doc["audit_id"])

    answer_svc = AnswerService(s3)
    for row in manifest.get("answers", []):
        answer_svc.upsert_answer(
            org_id,
            audit_id,
            project_id,
            ai_system_id,
            row["question_id"],
            row["answer"],
            state=row.get("state", "draft"),
            user="synthetic_seed",
        )

    now = utc_now()
    for ai_row in manifest.get("ai_analysis", []):
        qid = ai_row["question_id"]
        ans = answer_svc.get_answer(org_id, audit_id, qid, project_id, ai_system_id)
        ver = int((ans or {}).get("version") or 0)
        payload = {
            "question_id": qid,
            "last_analyzed_version": ver,
            "analyzed_at": now,
            "risk_level": ai_row.get("risk_level", "medium"),
            "confidence": ai_row.get("confidence", 0.8),
            "gap_report": ai_row.get("gap_report", {}),
        }
        s3.write_json(ai_key(org_id, audit_id, qid, project_id, ai_system_id), payload)
        if ver > 0:
            sync_ai_analysis_index(
                s3,
                org_id,
                audit_id,
                question_id=qid,
                last_analyzed_version=ver,
                project_id=project_id,
                ai_system_id=ai_system_id,
            )

    auditor_svc = AuditorService(s3)
    for fb in manifest.get("auditor_feedback", []):
        qid = fb["question_id"]
        ans = answer_svc.get_answer(org_id, audit_id, qid, project_id, ai_system_id)
        if not ans:
            continue
        auditor_svc.update_feedback(
            org_id,
            audit_id,
            qid,
            {
                "version": ans["version"],
                "auditor_id": "synthetic_auditor",
                "auditor_name": "Seed Auditor",
                "review_state": fb["review_state"],
                "summary": fb.get("summary"),
                "feedback": fb.get("feedback") or [],
                "recommendations": fb.get("recommendations") or [],
            },
            project_id,
            ai_system_id,
        )

    total_q = len(manifest.get("answers", []))
    AuditLifecycleService(s3).patch_metadata(
        org_id,
        audit_id,
        {"total_questions": total_q},
        project_id,
        ai_system_id,
    )
    AuditLifecycleService(s3).recompute_audit_summary(
        org_id,
        audit_id,
        project_id,
        ai_system_id,
        total_questions_hint=total_q,
    )

    pipe = PipelineService(s3)
    pcfg = manifest.get("pipeline", {})
    pipe.upsert_record(
        {
            "org_id": org_id,
            "audit_id": audit_id,
            "project_id": project_id,
            "ai_system_id": ai_system_id,
            "org_name": org_cfg["name"],
            "ai_system_name": sys_cfg.get("name", ai_system_id),
            "stage": pcfg.get("stage", PipelineStage.IN_PROGRESS.value),
            "total_questions": pcfg.get("total_questions", total_q),
            "answered_questions": pcfg.get("answered_questions", 2),
            "gap_analysis_status": pcfg.get(
                "gap_analysis_status", GapAnalysisStatus.COMPLETED.value
            ),
            "gap_analysis_progress": pcfg.get("gap_analysis_progress", 100),
            "gap_analysis_total": pcfg.get("gap_analysis_total", total_q),
            "gap_analysis_completed": pcfg.get("gap_analysis_completed", total_q),
            "created_at": now,
            "updated_at": now,
        }
    )

    gap_stub = manifest.get("gap_report_stub", {})
    question_results: List[Dict[str, Any]] = []
    for ai_row in manifest.get("ai_analysis", []):
        qid = ai_row["question_id"]
        gr = ai_row.get("gap_report") or {}
        question_results.append(
            {
                "question_id": qid,
                "match_score": gr.get("match_score", 0.7),
                "status": "ok",
            }
        )
    report = {
        "org_id": org_id,
        "audit_id": audit_id,
        "project_id": project_id,
        "ai_system_id": ai_system_id,
        "total_questions": total_q,
        "analyzed_count": len(question_results),
        "average_match_score": gap_stub.get("average_match_score", 0.7),
        "questions": question_results,
        "completed_at": now,
    }
    pipe.save_gap_report(org_id, audit_id, report, project_id, ai_system_id)

    if write_gap_index:
        _update_gap_index(
            s3,
            {
                "org_id": org_id,
                "audit_id": audit_id,
                "project_id": project_id,
                "ai_system_id": ai_system_id,
                "ai_system_name": sys_cfg.get("name", ai_system_id),
            },
        )

    if write_review_stub:
        review_svc = ReviewService(s3)
        review_svc._upsert_index_entry(
            org_id,
            {
                "org_id": org_id,
                "audit_id": audit_id,
                "project_id": project_id,
                "ai_system_id": ai_system_id,
                "status": "in_review",
                "org_name": org_cfg["name"],
            },
        )
        try:
            review_svc.save_opinion(
                org_id,
                manifest["answers"][0]["question_id"],
                "clean",
                "synthetic_csap",
                note="Synthetic seed opinion",
            )
        except Exception:
            pass

    extra_rows: List[Dict[str, Any]] = []
    for extra in manifest.get("additional_systems") or []:
        sid = str(extra.get("system_id") or "").strip()
        if not sid:
            continue
        body = {
            "project_id": project_id,
            "project_name": proj_cfg["project_name"],
            "system_id": sid,
            "name": extra.get("name", sid),
            "description": extra.get("description", ""),
            "version": extra.get("version", "v1"),
            "status": extra.get("status", "in_progress"),
        }
        doc = ops.add_ai_system(org_id, body)
        extra_rows.append(
            {
                "system_id": str(doc.get("system_id") or sid),
                "audit_id": str(doc.get("audit_id", "")),
                "name": doc.get("name", body["name"]),
            }
        )

    from app.etl.s3.utils import s3_paths as s3_paths_mod

    out: Dict[str, Any] = {
        "bucket": s3.bucket,
        "base_prefix": s3_paths_mod.BASE_PREFIX,
        "org_id": org_id,
        "audit_id": audit_id,
        "project_id": project_id,
        "ai_system_id": ai_system_id,
        "question_ids": [r["question_id"] for r in manifest.get("answers", [])],
        "gap_reports_index_key": GAP_REPORTS_INDEX_KEY,
    }
    if extra_rows:
        out["additional_systems"] = extra_rows
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed S3 with synthetic audit data (v2 layout)")
    parser.add_argument("--bucket", default=None, help="S3 bucket (default: config ai_assessment.s3.bucket)")
    parser.add_argument(
        "--prefix",
        default="",
        help="Optional key prefix (sets s3_paths.BASE_PREFIX), e.g. dev/synthetic/",
    )
    parser.add_argument(
        "--firm-demo",
        action="store_true",
        help="Use firm_demo_manifest.json (Risk Firm + riskfirm.com + systems 0001–0003)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Manifest JSON path (default: synthetic_manifest.json, or firm demo if --firm-demo)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load manifest and print plan only (no S3 writes)",
    )
    parser.add_argument(
        "--no-gap-index",
        action="store_true",
        help="Skip updating indexes/gap_reports_index.json",
    )
    parser.add_argument(
        "--no-review-stub",
        action="store_true",
        help="Skip reviews/index.json and sample opinion",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON summary of created identifiers to this path",
    )
    args = parser.parse_args()

    manifest_path = args.manifest
    if manifest_path is None:
        manifest_path = _FIRM_DEMO_MANIFEST if args.firm_demo else _MANIFEST_PATH

    if not manifest_path.is_file():
        print(f"Manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    manifest = _load_manifest(manifest_path)

    if args.dry_run:
        print(
            "Dry run: would create organization, project, primary AI system (+ optional additional_systems), "
            "answers, AI blobs, pipeline, gap report."
        )
        print(json.dumps(manifest, indent=2)[:2000])
        return 0

    if args.prefix:
        import app.etl.s3.utils.s3_paths as s3_paths_mod

        p = args.prefix.strip()
        if p and not p.endswith("/"):
            p = f"{p}/"
        s3_paths_mod.BASE_PREFIX = p

    from app.config import get_config
    from app.etl.s3.services.s3_client import S3Client

    bucket = args.bucket or get_config().ai_assessment.s3.bucket
    s3 = S3Client(bucket=bucket)

    summary = run_seed(
        s3,
        manifest,
        write_gap_index=not args.no_gap_index,
        write_review_stub=not args.no_review_stub,
    )

    out = json.dumps(summary, indent=2)
    print(out)
    if args.output:
        args.output.write_text(out, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
