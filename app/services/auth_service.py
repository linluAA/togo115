from __future__ import annotations

from fastapi import HTTPException, Response

from app.auth import authenticate, login_response, logout_response, update_credentials
from app.db import add_log


def login_user(response: Response, username: str, password: str) -> dict[str, bool]:
    if not authenticate(username, password):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    login_response(response, username)
    add_log("info", "auth", "用户登录成功", {"username": username})
    return {"ok": True}


def logout_user(response: Response, user: dict) -> dict[str, bool]:
    logout_response(response)
    add_log("info", "auth", "用户已退出", {"username": user["username"]})
    return {"ok": True}


def change_credentials(response: Response, user: dict, username: str, password: str) -> dict[str, bool]:
    update_credentials(username, password)
    # Force re-login with the new credentials.
    logout_response(response)
    add_log("warning", "auth", "账号密码已修改，已退出登录", {"old_username": user["username"], "new_username": username})
    return {"ok": True, "relogin_required": True}
