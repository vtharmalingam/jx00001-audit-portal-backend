"""CSAP review service — S3-backed storage for opinions, verdicts, and attestations."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.etl.s3.utils.s3_paths import _prefix


# ── S3 key helpers ────────────────────────────────────────────────────────────

def _review_key(project_id: str) -> str:
    return _prefix(f"reviews/{project_id}/review.json")


def _reviews_index_key() -> str:
    return _prefix("reviews/index.json")


# ── Opinion weights for trust score ──────────────────────────────────────────

OPINION_WEIGHTS = {
    "clean": 100,
    "qualified": 65,
    "adverse": 25,
    "disclaimer": 0,
}

VALID_OPINIONS = list(OPINION_WEIGHTS.keys())
VALID_VERDICTS = ["pass", "fail"]
VALID_ATTESTATIONS = VALID_OPINIONS  # same four options


def _compute_trust_score(opinions: List[Dict]) -> float:
    """Average of opinion weights across all reviewed questions."""
    if not opinions:
        return 0.0
    weights = [OPINION_WEIGHTS.get(o.get("opinion", ""), 0) for o in opinions]
    return round(sum(weights) / len(weights), 1)


def _suggest_attestation(trust_score: float) -> str:
    """Auto-suggest final attestation based on trust score."""
    if trust_score >= 90:
        return "clean"
    if trust_score >= 65:
        return "qualified"
    if trust_score >= 25:
        return "adverse"
    return "disclaimer"


class ReviewService:
    """CRUD for CSAP reviews stored in S3."""

    def __init__(self, s3):
        self.s3 = s3

    # ── Index (list of all reviews) ──────────────────────────────────────

    def _load_index(self) -> List[Dict]:
        data = self.s3.read_json(_reviews_index_key())
        if not data or not data.get("reviews"):
            return []
        return data["reviews"]

    def _save_index(self, reviews: List[Dict]) -> None:
        self.s3.write_json(
            _reviews_index_key(),
            {"reviews": reviews, "updated_at": datetime.utcnow().isoformat()},
        )

    def _upsert_index_entry(self, project_id: str, patch: Dict) -> None:
        index = self._load_index()
        for entry in index:
            if entry["project_id"] == project_id:
                entry.update(patch)
                entry["updated_at"] = datetime.utcnow().isoformat()
                self._save_index(index)
                return
        # New entry
        entry = {
            "project_id": project_id,
            "status": "in_review",
            "trust_score": 0,
            "attestation": None,
            "csap_user_id": None,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        entry.update(patch)
        index.append(entry)
        self._save_index(index)

    # ── Single review ────────────────────────────────────────────────────

    def _load_review(self, project_id: str) -> Dict:
        data = self.s3.read_json(_review_key(project_id))
        if not data:
            return {
                "project_id": project_id,
                "opinions": {},
                "verdicts": {},
                "attestation": None,
                "attestation_justification": None,
                "trust_score": 0,
                "csap_user_id": None,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
        return data

    def _save_review(self, project_id: str, review: Dict) -> None:
        review["updated_at"] = datetime.utcnow().isoformat()
        self.s3.write_json(_review_key(project_id), review)

    # ── Public API ───────────────────────────────────────────────────────

    def list_reviews(self) -> List[Dict]:
        return self._load_index()

    def get_review(self, project_id: str) -> Dict:
        return self._load_review(project_id)

    def save_opinion(
        self,
        project_id: str,
        question_id: str,
        opinion: str,
        csap_user_id: str,
        note: Optional[str] = None,
    ) -> Dict:
        """Save a per-question opinion (clean/qualified/adverse/disclaimer)."""
        if opinion not in VALID_OPINIONS:
            raise ValueError(f"Invalid opinion '{opinion}'. Must be one of: {VALID_OPINIONS}")

        review = self._load_review(project_id)
        review["csap_user_id"] = csap_user_id
        review["opinions"][question_id] = {
            "opinion": opinion,
            "csap_user_id": csap_user_id,
            "note": note,
            "updated_at": datetime.utcnow().isoformat(),
        }

        # Recalculate trust score
        review["trust_score"] = _compute_trust_score(list(review["opinions"].values()))
        self._save_review(project_id, review)

        # Update index
        self._upsert_index_entry(project_id, {
            "trust_score": review["trust_score"],
            "csap_user_id": csap_user_id,
            "status": "in_review",
        })
        return review

    def save_verdict(
        self,
        project_id: str,
        category_id: str,
        verdict: str,
        csap_user_id: str,
        note: Optional[str] = None,
    ) -> Dict:
        """Save a per-category verdict (pass/fail)."""
        if verdict not in VALID_VERDICTS:
            raise ValueError(f"Invalid verdict '{verdict}'. Must be one of: {VALID_VERDICTS}")

        review = self._load_review(project_id)
        review["csap_user_id"] = csap_user_id
        review["verdicts"][category_id] = {
            "verdict": verdict,
            "csap_user_id": csap_user_id,
            "note": note,
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._save_review(project_id, review)

        self._upsert_index_entry(project_id, {
            "csap_user_id": csap_user_id,
            "status": "in_review",
        })
        return review

    def save_attestation(
        self,
        project_id: str,
        attestation: str,
        csap_user_id: str,
        justification: Optional[str] = None,
    ) -> Dict:
        """Save the final project attestation (clean/qualified/adverse/disclaimer)."""
        if attestation not in VALID_ATTESTATIONS:
            raise ValueError(f"Invalid attestation '{attestation}'. Must be one of: {VALID_ATTESTATIONS}")

        review = self._load_review(project_id)
        review["csap_user_id"] = csap_user_id
        review["attestation"] = attestation
        review["attestation_justification"] = justification
        self._save_review(project_id, review)

        self._upsert_index_entry(project_id, {
            "trust_score": review["trust_score"],
            "attestation": attestation,
            "csap_user_id": csap_user_id,
            "status": "attested",
        })
        return review

    def get_trust_score(self, project_id: str) -> Dict:
        """Return the trust score and suggested attestation."""
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
