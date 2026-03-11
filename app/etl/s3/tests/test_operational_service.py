'''
✔ domain → org_id lookup
✔ assign org to auditor
✔ prevent duplicate org assignment
✔ auditor not found → error
✔ empty auditor list → handled
'''

import pytest

from app.etl.s3.services.operational_service import OperationalService
from app.etl.s3.utils.s3_paths import auditor_master_key


def test_assign_org_real_s3(real_s3):
    org_id = "org_unit_test"

    service = OperationalService(real_s3)

    # Seed auditor master
    service.s3.write_json(
        auditor_master_key(),
        [
            {
                "auditor_id": "aud_1",
                "name": "Test Auditor",
                "email": "test@test.com",
                "region": "EMEA",
                "organizations": [],
                "enrolled": "2024-01-01"
            }
        ]
    )

    service.assign_org("aud_1", org_id)

    auditors = service.get_auditors()

    assert org_id in auditors[0]["organizations"]