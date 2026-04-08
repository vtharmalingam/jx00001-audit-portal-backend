"""CSAP review service — S3-backed storage for opinions, verdicts, and attestations.

Purpose: CSAP-style review — review.json under audit current/, global reviews/index.json,
opinions/verdicts/attestations and trust-score helpers.

Review data is stored at:
  organizations/{org}/projects/{proj}/systems/{sys}/audits/{audit_id}/current/review.json

The global review index (for CSAP queue listing) remains at:
  reviews/index.json
"""

from typing import Any, Dict, List, Optional

from app.etl.s3.utils.helpers import utc_now

from app.etl.s3.utils.s3_paths import review_key as _audit_review_key, reviews_index_key


# ── Opinion weights for trust score ──────────────────────────────────────────

OPINION_WEIGHTS = {
    "clean": 100,
    "qualified": 65,
    "adverse": 25,
    "disclaimer": 0,
}

VALID_OPINIONS = list(OPINION_WEIGHTS.keys())
VALID_VERDICTS = ["pass", "fail"]
VALID_ATTESTATIONS = VALID_OPINIONS


def _compute_trust_score(opinions: List[Dict]) -> float:
    if not opinions:
        return 0.0
    weights = [OPINION_WEIGHTS.get(o.get("opinion", ""), 0) for o in opinions]
    return round(sum(weights) / len(weights), 1)


def _suggest_attestation(trust_score: float) -> str:
    if trust_score >= 90:
        return "clean"
    if trust_score >= 65:
        return "qualified"
    if trust_score >= 25:
        return "adverse"
    return "disclaimer"


class ReviewService:
    def __init__(self, s3):
        self.s3 = s3

    # ── Review key resolution ───────────────────────────────────────────────

    def _resolve_review_key(self, org_id: str) -> str:
        """Resolve review.json path from the CSAP queue row (org + ULID audit + 3/4-digit scope)."""
        index = self._load_index()
        for entry in index:
            if entry.get("org_id") != org_id:
                continue
            oid = str(entry.get("org_id") or "")
            pid = str(entry.get("project_id") or "")
            sid = str(entry.get("ai_system_id") or "")
            aid = str(entry.get("audit_id") or "")
            if len(pid) == 3 and pid.isdigit() and len(sid) == 4 and sid.isdigit() and len(aid) == 26:
                return _audit_review_key(oid, aid, pid, sid)

        raise ValueError(
            f"No review index entry for org_id={org_id!r} with audit_id, project_id, ai_system_id; "
            "complete gap analysis first so the queue row is written."
        )

    # ── Index (global list for CSAP queue) ──────────────────────────────────

    def _load_index(self) -> List[Dict]:
        data = self.s3.read_json(reviews_index_key())
        if not data or not data.get("reviews"):
            return []
        return data["reviews"]

    def _save_index(self, reviews: List[Dict]) -> None:
        self.s3.write_json(
            reviews_index_key(),
            {"reviews": reviews, "updated_at": utc_now()},
        )

    def _upsert_index_entry(self, org_id: str, patch: Dict) -> None:
        index = self._load_index()
        for entry in index:
            if entry.get("org_id") == org_id:
                entry.update(patch)
                entry["updated_at"] = utc_now()
                self._save_index(index)
                return
        entry = {
            "org_id": org_id,
            "status": "in_review",
            "trust_score": 0,
            "attestation": None,
            "csap_user_id": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        entry.update(patch)
        index.append(entry)
        self._save_index(index)

    # ── Single review ────────────────────────────────────────────────────────

    def _load_review(self, project_id: str) -> Dict:
        key = self._resolve_review_key(project_id)
        data = self.s3.read_json(key)
        if not data:
            return {
                "project_id": project_id,
                "opinions": {},
                "verdicts": {},
                "attestation": None,
                "attestation_justification": None,
                "trust_score": 0,
                "csap_user_id": None,
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
        return data

    def _save_review(self, project_id: str, review: Dict) -> None:
        key = self._resolve_review_key(project_id)
        review["updated_at"] = utc_now()
        self.s3.write_json(key, review)

    # ── Public API ───────────────────────────────────────────────────────────

    def list_reviews(self) -> List[Dict]:
        return self._load_index()

    def get_review(self, project_id: str) -> Dict:
        return self._load_review(project_id)

    def get_review_with_context(self, org_id: str) -> Dict:
        """Return review data together with audit identifiers from the index entry."""
        index = self._load_index()
        audit_context: Dict = {}
        for entry in index:
            if entry.get("org_id") == org_id:
                audit_context = {
                    "audit_id": entry.get("audit_id"),
                    "project_id": entry.get("project_id"),
                    "ai_system_id": entry.get("ai_system_id"),
                    "org_name": entry.get("org_name", ""),
                    "total_questions": entry.get("total_questions"),
                    "gap_analysis_score": entry.get("gap_analysis_score"),
                }
                break
        review = self._load_review(org_id)
        return {"review": review, "audit_context": audit_context}

    def save_opinion(self, project_id: str, question_id: str, opinion: str, csap_user_id: str, note: Optional[str] = None) -> Dict:
        if opinion not in VALID_OPINIONS:
            raise ValueError(f"Invalid opinion '{opinion}'. Must be one of: {VALID_OPINIONS}")
        review = self._load_review(project_id)
        review["csap_user_id"] = csap_user_id
        review["opinions"][question_id] = {
            "opinion": opinion, "csap_user_id": csap_user_id,
            "note": note, "updated_at": utc_now(),
        }
        review["trust_score"] = _compute_trust_score(list(review["opinions"].values()))
        self._save_review(project_id, review)
        self._upsert_index_entry(project_id, {
            "trust_score": review["trust_score"], "csap_user_id": csap_user_id, "status": "in_review",
        })
        return review

    def save_verdict(self, project_id: str, category_id: str, verdict: str, csap_user_id: str, note: Optional[str] = None) -> Dict:
        if verdict not in VALID_VERDICTS:
            raise ValueError(f"Invalid verdict '{verdict}'. Must be one of: {VALID_VERDICTS}")
        review = self._load_review(project_id)
        review["csap_user_id"] = csap_user_id
        review["verdicts"][category_id] = {
            "verdict": verdict, "csap_user_id": csap_user_id,
            "note": note, "updated_at": utc_now(),
        }
        self._save_review(project_id, review)
        self._upsert_index_entry(project_id, {"csap_user_id": csap_user_id, "status": "in_review"})
        return review

    def save_attestation(self, project_id: str, attestation: str, csap_user_id: str, justification: Optional[str] = None) -> Dict:
        if attestation not in VALID_ATTESTATIONS:
            raise ValueError(f"Invalid attestation '{attestation}'. Must be one of: {VALID_ATTESTATIONS}")
        review = self._load_review(project_id)
        review["csap_user_id"] = csap_user_id
        review["attestation"] = attestation
        review["attestation_justification"] = justification
        self._save_review(project_id, review)
        self._upsert_index_entry(project_id, {
            "trust_score": review["trust_score"], "attestation": attestation,
            "csap_user_id": csap_user_id, "status": "attested",
        })
        return review

    def get_trust_score(self, project_id: str) -> Dict:
        review = self._load_review(project_id)
        score = review.get("trust_score", 0)
        return {
            "project_id": project_id,
            "trust_score": score,
            "suggested_attestation": _suggest_attestation(score),
            "total_opinions": len(review.get("opinions", {})),
            "total_verdicts": len(review.get("verdicts", {})),
            "attestation": review.get("attestation"),
        }
