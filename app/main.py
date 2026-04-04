from datetime import datetime
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import auth_router, role_router
from app.rest.v1 import (
    admin_s3_router,
    admin_tests_router,
    assessment_router,
    knowledge_router,
    organizations_router,
    aict_users_router,
    review_router,
)
from app.pipeline import pipeline_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting audit portal API...")
    app.state.start_time = datetime.utcnow()

    # Seed missing demo users (idempotent — skips existing)
    try:
        from app.auth.service import AuthUserService
        from app.rest.deps import s3_client as _s3
        svc = AuthUserService(_s3)
        n = svc.ensure_demo_users()
        if n:
            print(f"  Seeded {n} demo user(s)")
    except Exception as e:
        print(f"  Warning: demo user seed failed: {e}")

    yield
    print("Shutting down audit portal API...")


app = FastAPI(
    title="Audit Portal API",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "organizations", "description": "Org profiles, onboarding, AI systems."},
        {"name": "assessment", "description": "Categories, questions, answers, evaluation, audit views."},
        {"name": "knowledge", "description": "Semantic search and gap analysis."},
        {"name": "admin", "description": "Admin-only operational endpoints."},
        {"name": "pipeline", "description": "Pipeline stages, submission, gap analysis."},
    ],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({"detail": exc.errors(), "body": exc.body}),
    )


origins = [
    "http://localhost",
    "http://localhost:8080",
    "http://localhost:3000",
    "http://100.49.55.139:90",
    "http://100.49.55.139",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(role_router, prefix=API_PREFIX)
app.include_router(organizations_router, prefix=API_PREFIX)
app.include_router(aict_users_router, prefix=API_PREFIX)
app.include_router(assessment_router, prefix=API_PREFIX)
app.include_router(knowledge_router, prefix=API_PREFIX, include_in_schema=False)
app.include_router(admin_tests_router, prefix=API_PREFIX, include_in_schema=False)
app.include_router(review_router, prefix=API_PREFIX)
app.include_router(admin_s3_router, prefix=API_PREFIX, include_in_schema=False)
app.include_router(pipeline_router, prefix=API_PREFIX)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
    )
