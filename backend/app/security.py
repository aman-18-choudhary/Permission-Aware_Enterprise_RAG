import base64
import hashlib
import time

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

COOKIE = "sb_session"
SESSION_TTL = 60 * 60 * 24 * 7


def _fernet() -> Fernet:
    key = hashlib.sha256(("fernet:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def sign(payload: dict, ttl: int = SESSION_TTL) -> str:
    return jwt.encode({**payload, "exp": int(time.time()) + ttl}, get_settings().secret_key, algorithm="HS256")


def verify(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    data = verify(request.cookies.get(COOKIE, ""))
    user = db.get(User, data["uid"]) if data and data.get("kind") == "session" else None
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admin only")
    return user


def set_session(response, user: User) -> None:
    secure = get_settings().env == "prod"
    response.set_cookie(
        COOKIE, sign({"uid": user.id, "kind": "session"}), httponly=True, samesite="lax", secure=secure, max_age=SESSION_TTL, path="/"
    )
