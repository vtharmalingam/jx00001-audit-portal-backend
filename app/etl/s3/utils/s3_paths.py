# utils/s3_paths.py
#
# New folder structure (v2):
#   organizations/{ULID}/
#       org_profile.json
#       projects/{seq_001}/
#           project.json
#           ai_systems/
#               {seq_0001}/
#                   system.json
#                   audits/
#                       {ULID-001-0001}/
#                           current/
#                               answers/{Q1}.json
#                               ai_analysis/{Q1}.json
#                               auditor_feedback/{Q1}.json
#                               evidence/{Q1}/...
#                               gap_report.json
#                               pipeline.json
#                               review.json
#                               metadata.json
#                               timeline.json
#                               progress.json
#                               evidence_index.json
#                               audit_summary.json

BASE_PREFIX = ""  # e.g. "unit_test/" in tests; empty in prod


def _prefix(path: str) -> str:
    return f"{BASE_PREFIX}{path}"


# ── Organization ─────────────────────────────────────────────────────────────

def org_root(org_id: str) -> str:
    return _prefix(f"organizations/{org_id}")


def org_profile_key(org_id: str) -> str:
    return f"{org_root(org_id)}/org_profile.json"


# ── Project ──────────────────────────────────────────────────────────────────

def projects_prefix(org_id: str) -> str:
    return f"{org_root(org_id)}/projects/"


def project_root(org_id: str, project_id: str) -> str:
    return f"{org_root(org_id)}/projects/{project_id}"


def project_json_key(org_id: str, project_id: str) -> str:
    return f"{project_root(org_id, project_id)}/project.json"


# ── AI System ────────────────────────────────────────────────────────────────

def ai_systems_prefix(org_id: str, project_id: str) -> str:
    return f"{project_root(org_id, project_id)}/ai_systems/"


def system_root(org_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{project_root(org_id, project_id)}/ai_systems/{ai_system_id}"


def system_json_key(org_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{system_root(org_id, project_id, ai_system_id)}/system.json"


# ── Audit ────────────────────────────────────────────────────────────────────

def make_audit_id(org_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{org_id}-{project_id}-{ai_system_id}"


def audit_root(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{system_root(org_id, project_id, ai_system_id)}/audits/{audit_id}"


def current_prefix(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/current"


# ── Answers ──────────────────────────────────────────────────────────────────

def answers_prefix(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/answers/"


def answer_key(org_id: str, audit_id: str, question_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/answers/{question_id}.json"


# ── AI Analysis (gap analysis per question) ──────────────────────────────────

def ai_prefix(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/ai_analysis/"


def ai_key(org_id: str, audit_id: str, question_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/ai_analysis/{question_id}.json"


# ── Auditor Feedback ─────────────────────────────────────────────────────────

def auditor_key(org_id: str, audit_id: str, question_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/auditor_feedback/{question_id}.json"


# ── Gap Report (full assessment) ─────────────────────────────────────────────

def gap_report_key(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/gap_report.json"


# ── Pipeline State ───────────────────────────────────────────────────────────

def pipeline_key(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/pipeline.json"


# ── Review (CSAP) ───────────────────────────────────────────────────────────

def review_key(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/review.json"


# ── Metadata & Timeline ─────────────────────────────────────────────────────

def audit_metadata_key(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/metadata.json"


def audit_summary_key(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/audit_summary.json"


def timeline_key(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/timeline.json"


def progress_key(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/progress.json"


# ── Evidence ─────────────────────────────────────────────────────────────────

def evidence_index_key(org_id: str, audit_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/evidence_index.json"


def evidence_prefix(org_id: str, audit_id: str, question_id: str, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/evidence/{question_id}/"


def evidence_object_key(
    org_id: str, audit_id: str, question_id: str, file_name: str,
    project_id: str = "0", ai_system_id: str = "0",
) -> str:
    safe = str(file_name).replace("..", "").lstrip("/")
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/evidence/{question_id}/{safe}"


# ── Rounds ───────────────────────────────────────────────────────────────────

def round_prefix(org_id: str, audit_id: str, round_n: int, project_id: str = "0", ai_system_id: str = "0") -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/rounds/round_{int(round_n)}/"


# ── Lookups (global) ─────────────────────────────────────────────────────────

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


def aict_users_key() -> str:
    return _prefix("platform/aict_users.json")


# ── Review Index (global for CSAP queue) ─────────────────────────────────────

def reviews_index_key() -> str:
    return _prefix("reviews/index.json")
