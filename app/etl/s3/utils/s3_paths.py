# utils/s3_paths.py

# FOR 
BASE_PREFIX = "" #  "unit_test/" for Test and  empty in prod
 

def _prefix(path: str) -> str:
    return f"{BASE_PREFIX}{path}"

def answer_key(org_id, audit_id, question_id):
    return _prefix(
        f"organizations/{org_id}/audits/{audit_id}/current/answers/{question_id}.json"
    )

def answers_prefix(org_id, audit_id):
    return _prefix(
        f"organizations/{org_id}/audits/{audit_id}/current/answers/"
    )

def ai_key(org_id, audit_id, question_id):
    return _prefix(
        f"organizations/{org_id}/audits/{audit_id}/current/ai_analysis/{question_id}.json"
    )

def ai_prefix(org_id, audit_id):
    return _prefix(
        f"organizations/{org_id}/audits/{audit_id}/current/ai_analysis/"
    )


def auditor_key(org_id, audit_id, question_id):
    return _prefix(
        f"organizations/{org_id}/audits/{audit_id}/current/auditor_feedback/{question_id}.json"
    )

def audit_metadata_key(org_id, audit_id):
    return _prefix(
        f"organizations/{org_id}/audits/{audit_id}/metadata.json"
    )


def domain_lookup_key(domain):
    return _prefix(f"lookups/domains/{domain}.json")

def auditor_master_key():
    return _prefix("lookups/auditor_master.json")