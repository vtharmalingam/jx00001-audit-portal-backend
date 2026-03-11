# services/operational_service.py

from typing import List, Dict, Optional
from app.etl.s3.utils.s3_paths import domain_lookup_key, auditor_master_key
from datetime import datetime



class OperationalService:

    def __init__(self, s3):
        self.s3 = s3

    # 🔹 A. Get org_id from domain
    def get_org_by_domain(self, domain: str) -> Optional[str]:
        data = self.s3.read_json(domain_lookup_key(domain))
        if not data:
            return None
        return data.get("org_id")

    # 🔹 B. Get all auditors
    def get_auditors(self) -> List[Dict]:
        data = self.s3.read_json(auditor_master_key())
        return data if data else []

    # 🔹 C. Assign org to auditor
    def assign_org(self, auditor_id: str, org_id: str) -> Dict:
        auditors = self.get_auditors()

        if not auditors:
            raise ValueError("Auditor master is empty")

        updated = False

        for auditor in auditors:
            if auditor.get("auditor_id") == auditor_id:

                # Ensure organizations field exists
                if "organizations" not in auditor:
                    auditor["organizations"] = []

                # Avoid duplicates
                if org_id not in auditor["organizations"]:
                    auditor["organizations"].append(org_id)

                updated = True
                break

        if not updated:
            raise ValueError(f"Auditor {auditor_id} not found")

        self.s3.write_json(auditor_master_key(), auditors)

        return {
            "status": "success",
            "auditor_id": auditor_id,
            "org_id": org_id
        }



    # While organization onboarded, 'org_profile' will get updated.
    def upsert_org_profile(
        self,
        org_id: str,
        name: str,
        email: str,
        status: str = "pending"
    ) -> Dict:

        if not org_id:
            raise ValueError("org_id is required")

        key = f"organizations/{org_id}/org_profile.json"

        existing = self.s3.read_json(key) or {}

        data = {
            "org_id": org_id,
            "name": name,
            "email": email,
            "status": status,
            "updated_at": datetime.utcnow().isoformat()
        }

        # 🔹 preserve created_at if exists
        if existing.get("created_at"):
            data["created_at"] = existing["created_at"]
        else:
            data["created_at"] = datetime.utcnow().isoformat()

        self.s3.write_json(key, data)

        return data



    # This method is used by Auditor desk (to list organization given auditor)
    # TODO: For a given org_id instead?
    def get_all_organizations(self) -> List[Dict]:

        prefix = "organizations/"

        results = []
        continuation_token = None
        seen_orgs = set()

        while True:
            params = {
                "Bucket": self.s3.bucket,
                "Prefix": prefix,
                "Delimiter": "/"
            }

            if continuation_token:
                params["ContinuationToken"] = continuation_token

            response = self.s3.client.list_objects_v2(**params)

            # 🔹 Extract org folders
            for cp in response.get("CommonPrefixes", []):
                org_prefix = cp.get("Prefix")  # e.g., organizations/D01/
                org_id = org_prefix.split("/")[1]

                if org_id in seen_orgs:
                    continue

                seen_orgs.add(org_id)

                # 🔹 Read org profile
                key = f"{org_prefix}org_profile.json"
                profile = self.s3.read_json(key)

                if profile:
                    results.append({
                        "name": profile.get("name"),
                        "email": profile.get("email"),
                        "org_id": profile.get("org_id"),
                        "status": profile.get("status", "pending")
                    })
                else:
                    # fallback if profile missing
                    results.append({
                        "name": org_id,
                        "email": None,
                        "org_id": org_id,
                        "status": "pending"
                    })

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        # Optional: sort by name
        results.sort(key=lambda x: x.get("name") or "")

        return results        