# utils/s3_paths.py

BASE_PREFIX = ""  # e.g. "unit_test/" in tests; empty in prod


def _prefix(path: str) -> str:
    return f"{BASE_PREFIX}{path}"


def _norm_scope(project_id, ai_system_id) -> tuple[str, str]:
    p = str(project_id if project_id is not None else "0")
    s = str(ai_system_id if ai_system_id is not None else "0")
    return p, s


def audit_root(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    """Prefix for one audit (no trailing slash), always in v2 nested layout."""
    p, s = _norm_scope(project_id, ai_system_id)
    oid, aid = str(org_id), str(audit_id)
    return _prefix(f"organizations/{oid}/projects/{p}/ai_systems/{s}/audits/{aid}")


def current_prefix(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/current"


def answer_key(
    org_id: str,
    audit_id: str,
    question_id: str,
    project_id: str = "0",
    ai_system_id: str = "0",
) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/answers/{question_id}.json"


def answers_prefix(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/answers/"


def ai_key(
    org_id: str,
    audit_id: str,
    question_id: str,
    project_id: str = "0",
    ai_system_id: str = "0",
) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/ai_analysis/{question_id}.json"


def ai_prefix(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/ai_analysis/"


def auditor_key(
    org_id: str,
    audit_id: str,
    question_id: str,
    project_id: str = "0",
    ai_system_id: str = "0",
) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/auditor_feedback/{question_id}.json"


def audit_metadata_key(
    org_id: str,
    audit_id: str,
    project_id: str = "0",
    ai_system_id: str = "0",
) -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/metadata.json"


def audit_summary_key(
    org_id: str,
    audit_id: str,
    project_id: str = "0",
    ai_system_id: str = "0",
) -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/audit_summary.json"


def timeline_key(
    org_id: str,
    audit_id: str,
    project_id: str = "0",
    ai_system_id: str = "0",
) -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/timeline.json"


def progress_key(
    org_id: str,
    audit_id: str,
    project_id: str = "0",
    ai_system_id: str = "0",
) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/progress.json"


def evidence_index_key(
    org_id: str,
    audit_id: str,
    project_id: str = "0",
    ai_system_id: str = "0",
) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/evidence_index.json"


def evidence_prefix(
    org_id: str,
    audit_id: str,
    question_id: str,
    project_id: str = "0",
    ai_system_id: str = "0",
) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/evidence/{question_id}/"


def evidence_object_key(
    org_id: str,
    audit_id: str,
    question_id: str,
    file_name: str,
    project_id: str = "0",
    ai_system_id: str = "0",
) -> str:
    safe = str(file_name).replace("..", "").lstrip("/")
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/evidence/{question_id}/{safe}"


def round_prefix(
    org_id: str,
    audit_id: str,
    round_n: int,
    project_id: str = "0",
    ai_system_id: str = "0",
) -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/rounds/round_{int(round_n)}/"


def project_json_key(org_id: str, project_id: str) -> str:
    return _prefix(f"organizations/{org_id}/projects/{project_id}/project.json")


def projects_prefix(org_id: str) -> str:
    return _prefix(f"organizations/{org_id}/projects/")


def system_json_key(org_id: str, project_id: str, ai_system_id: str) -> str:
    return _prefix(
        f"organizations/{org_id}/projects/{project_id}/ai_systems/{ai_system_id}/system.json"
    )


def domain_lookup_key(domain: str) -> str:
    return _prefix(f"lookups/domains/{domain}.json")


def org_lookup_key(org_id: str) -> str:
    return _prefix(f"lookups/organizations/{org_id}.json")


def ai_system_lookup_key(ai_system_id: str) -> str:
    return _prefix(f"lookups/ai_systems/{ai_system_id}.json")


def blockchain_export_key(audit_id: str) -> str:
    return _prefix(f"exports/blockchain/{audit_id}.json")


def auditor_master_key() -> str:
    return _prefix("lookups/auditor_master.json")
