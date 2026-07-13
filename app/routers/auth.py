from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.auth import current_user
from app.schemas import ChangeCredentialsRequest, LoginRequest
from app.services.auth_service import change_credentials, login_user, logout_user

router = APIRouter()


@router.post("/api/auth/login")
async def login(payload: LoginRequest, response: Response) -> dict:
    return login_user(response, payload.username, payload.password)


@router.post("/api/auth/logout")
async def logout(response: Response, user: dict = Depends(current_user)) -> dict:
    return logout_user(response, user)


@router.get("/api/auth/me")
async def me(user: dict = Depends(current_user)) -> dict:
    return user


@router.put("/api/auth/credentials")
async def credentials(payload: ChangeCredentialsRequest, response: Response, user: dict = Depends(current_user)) -> dict:
    return change_credentials(response, user, payload.username, payload.password)
