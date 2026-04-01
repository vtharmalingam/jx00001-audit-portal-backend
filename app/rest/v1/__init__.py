from app.rest.v1.assessment import router as assessment_router
from app.rest.v1.admin_tests import router as admin_tests_router
from app.rest.v1.admin_s3 import router as admin_s3_router
from app.rest.v1.knowledge import router as knowledge_router
from app.rest.v1.organizations import router as organizations_router

__all__ = [
    "assessment_router",
    "knowledge_router",
    "organizations_router",
    "admin_tests_router",
    "admin_s3_router",
]
