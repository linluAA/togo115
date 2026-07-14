from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeSerializer, URLSafeTimedSerializer

from app.config import settings
from app.db import db, hash_password, row_to_dict, utc_now, verify_password

serializer = URLSafeSerializer(settings.secret_key, salt="togo115-session")
novnc_serializer = URLSafeTimedSerializer(settings.secret_key, salt="togo115-novnc")


def authenticate(username: str, password: str) -> bool:
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        return False
    return verify_password(password, user["password_hash"])


def login_response(response: Response, username: str) -> None:
    token = serializer.dumps({"username": username})
    response.set_cookie(
        settings.session_cookie,
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
    )


def logout_response(response: Response) -> None:
    response.delete_cookie(settings.session_cookie)


def current_user(request: Request) -> dict:
    token = request.cookies.get(settings.session_cookie)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = serializer.loads(token)
    except BadSignature as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效") from exc
    with db() as conn:
        user = conn.execute("SELECT id, username, created_at, updated_at FROM users WHERE username = ?", (payload["username"],)).fetchone()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return row_to_dict(user) or {}


def create_novnc_access_token() -> str:
    return novnc_serializer.dumps({"scope": "novnc"})


def verify_novnc_access_token(token: str | None, max_age: int = 60 * 60 * 12) -> bool:
    if not token:
        return False
    try:
        payload = novnc_serializer.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return False
    return payload.get("scope") == "novnc"


def update_credentials(username: str, password: str) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE users SET username = ?, password_hash = ?, updated_at = ? WHERE id = 1",
            (username, hash_password(password), utc_now()),
        )
