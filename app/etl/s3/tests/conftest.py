# tests/conftest.py

import pytest
from app.etl.s3.services.s3_client import S3Client
from app.etl.s3.utils.s3_paths import BASE_PREFIX
from app.etl.s3.tests.utils import delete_prefix

BUCKET = "audit-system-data-dev"

@pytest.fixture
def real_s3():
  
    s3 = S3Client(BUCKET)

    delete_prefix(s3, BUCKET, BASE_PREFIX)

    yield s3

    # optional: disable during debugging
    delete_prefix(s3, BUCKET, BASE_PREFIX)