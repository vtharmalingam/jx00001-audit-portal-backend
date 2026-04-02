from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.etl.s3.services.aict_users_service import AictUsersService
from app.rest.deps import s3_client

router = APIRouter(prefix="/aict/users", tags=["aict-users"])

VALID_ROLES = {"aict_admin", "aict_manager", "aict_practitioner"}


def _svc() -> AictUsersService:
    return AictUsersService(s3_client)


class UserCreateBody(BaseModel):
    id: Optional[str] = None
    name: str
    email: str
    role: str = "aict_manager"


class UserUpdateBody(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None


@router.get("", summary="List AICT platform users")
async def list_users():
    users = _svc().list_users()
    return {"users": users, "total": len(users)}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create AICT platform user")
async def create_user(body: UserCreateBody):
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_ROLE", "message": f"role must be one of {sorted(VALID_ROLES)}"},
        )
    user = _svc().create_user(
        name=body.name,
        email=body.email,
        role=body.role,
        user_id=body.id or None,
    )
    return {"user": user}


@router.patch("/{user_id}", summary="Update AICT platform user")
async def update_user(user_id: str, body: UserUpdateBody):
    if body.role is not None and body.role not in VALID_ROLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_ROLE", "message": f"role must be one of {sorted(VALID_ROLES)}"},
        )
    user = _svc().update_user(user_id, body.model_dump(exclude_none=True))
    if not user:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"User {user_id} not found"},
        )
    return {"user": user}


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete AICT platform user")
async def delete_user(user_id: str):
    deleted = _svc().delete_user(user_id)
    if not deleted:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"User {user_id} not found"},
        )
