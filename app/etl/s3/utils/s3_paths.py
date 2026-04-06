# utils/s3_paths.py
#
# Target layout (see app/etl/s3/README-datastruct.md):
#   organizations/{org_id}/projects/{project_id}/systems/{ai_system_id}/
#       system.json
#       audits/{audit_id}/          # audit_id = ULID only
#           metadata.json
#           audit_summary.json
#           timeline.json
#           current/…
#           derived/…

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


# ── System (per project) ─────────────────────────────────────────────────────

def systems_prefix(org_id: str, project_id: str) -> str:
    return f"{project_root(org_id, project_id)}/systems/"


def system_root(org_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{project_root(org_id, project_id)}/systems/{ai_system_id}"


def system_json_key(org_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{system_root(org_id, project_id, ai_system_id)}/system.json"


# ── Audit (audit_id = ULID) ─────────────────────────────────────────────────

def audit_root(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{system_root(org_id, project_id, ai_system_id)}/audits/{audit_id}"


def current_prefix(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/current"


def derived_prefix(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/derived"


# ── Answers ──────────────────────────────────────────────────────────────────

def answers_prefix(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/answers/"


def answers_index_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/answers/_index.json"


def answer_key(org_id: str, audit_id: str, question_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/answers/{question_id}.json"


# ── AI Analysis ──────────────────────────────────────────────────────────────

def ai_prefix(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/ai_analysis/"


def ai_analysis_index_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/ai_analysis/_index.json"


def ai_key(org_id: str, audit_id: str, question_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/ai_analysis/{question_id}.json"


# ── Auditor Feedback ─────────────────────────────────────────────────────────

def auditor_feedback_index_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/auditor_feedback/_index.json"


def auditor_key(org_id: str, audit_id: str, question_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/auditor_feedback/{question_id}.json"


# ── Gap report / pipeline / review ───────────────────────────────────────────

def gap_report_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/gap_report.json"


def pipeline_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/pipeline.json"


def review_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/review.json"


# ── Metadata & timeline (audit root) ─────────────────────────────────────────

def audit_metadata_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/metadata.json"


def audit_summary_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/audit_summary.json"


def timeline_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{audit_root(org_id, audit_id, project_id, ai_system_id)}/timeline.json"


def progress_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/progress.json"


# ── Evidence ─────────────────────────────────────────────────────────────────

def evidence_index_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/evidence_index.json"


def evidence_prefix(org_id: str, audit_id: str, question_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/evidence/{question_id}/"


def evidence_object_key(
    org_id: str, audit_id: str, question_id: str, file_name: str,
    project_id: str, ai_system_id: str,
) -> str:
    safe = str(file_name).replace("..", "").lstrip("/")
    return f"{current_prefix(org_id, audit_id, project_id, ai_system_id)}/evidence/{question_id}/{safe}"


# ── Derived (rebuildable) ────────────────────────────────────────────────────

def derived_metrics_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{derived_prefix(org_id, audit_id, project_id, ai_system_id)}/metrics.json"


def derived_risk_scores_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{derived_prefix(org_id, audit_id, project_id, ai_system_id)}/risk_scores.json"


def derived_insights_key(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{derived_prefix(org_id, audit_id, project_id, ai_system_id)}/insights.json"


def derived_embeddings_prefix(org_id: str, audit_id: str, project_id: str, ai_system_id: str) -> str:
    return f"{derived_prefix(org_id, audit_id, project_id, ai_system_id)}/embeddings/"


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


def platform_settings_key() -> str:
    return _prefix("platform/platform_settings.json")


def email_templates_prefix() -> str:
    return _prefix("platforms/email-templates/")


def email_template_key(scenario: str) -> str:
    return _prefix(f"platforms/email-templates/{scenario}.json")


def reviews_index_key() -> str:
    return _prefix("reviews/index.json")
