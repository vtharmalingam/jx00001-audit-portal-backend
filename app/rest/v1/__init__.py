from app.rest.v1.assessment import router as assessment_router
from app.rest.v1.knowledge import router as knowledge_router
from app.rest.v1.organizations import router as organizations_router

__all__ = ["assessment_router", "knowledge_router", "organizations_router"]
