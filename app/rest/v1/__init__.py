from app.rest.v1.assessment import router as assessment_router
from app.rest.v1.admin_tests import router as admin_tests_router
from app.rest.v1.admin_s3 import router as admin_s3_router
from app.rest.v1.knowledge import router as knowledge_router
from app.rest.v1.organizations import router as organizations_router
from app.rest.v1.aict_users import router as aict_users_router
from app.rest.v1.platform_settings import router as platform_settings_router
from app.rest.v1.review import router as review_router

__all__ = [
    "assessment_router",
    "knowledge_router",
    "organizations_router",
    "admin_tests_router",
    "admin_s3_router",
    "aict_users_router",
    "platform_settings_router",
    "review_router",
]
