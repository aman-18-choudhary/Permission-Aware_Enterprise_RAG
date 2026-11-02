import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Source, User
from ..security import COOKIE, current_user, encrypt, set_session, sign, verify

router = APIRouter(prefix="/auth", tags=["auth"])

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
LOGIN_SCOPES = "openid email profile"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
STATE_COOKIE = "sb_oauth_state"


def _redirect_uri() -> str:
    return f"{get_settings().public_url}/api/auth/callback"


def _start(purpose: str, scopes: str, extra: dict) -> RedirectResponse:
    s = get_settings()
    if not s.google_client_id:
        raise HTTPException(500, "Google OAuth is not configured")
    state = sign({"kind": "oauth", "purpose": purpose, "nonce": secrets.token_urlsafe(16)}, ttl=600)
    params = {
        "client_id": s.google_client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": scopes,
        "state": state,
        **extra,
    }
    resp = RedirectResponse(f"{AUTH_URL}?{urlencode(params)}")
    resp.set_cookie(STATE_COOKIE, state, httponly=True, samesite="lax", secure=s.env == "prod", max_age=600, path="/")
    return resp


@router.get("/login")
def login():
    return _start("login", LOGIN_SCOPES, {"prompt": "select_account"})


@router.get("/drive/connect")
def drive_connect(user: User = Depends(current_user)):
    # Incremental consent: Drive access is requested only when the user opts in.
    return _start(
        "drive",
        f"{LOGIN_SCOPES} {DRIVE_SCOPE}",
        {"access_type": "offline", "prompt": "consent", "login_hint": user.email},
    )


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", db: Session = Depends(get_db)):
    s = get_settings()
    cookie_state = request.cookies.get(STATE_COOKIE, "")
    data = verify(state)
    if not code or not state or not secrets.compare_digest(state, cookie_state) or not data or data.get("kind") != "oauth":
        raise HTTPException(400, "Invalid OAuth state")

    r = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri": _redirect_uri(),
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    if r.status_code != 200:
        raise HTTPException(400, "Google token exchange failed")
    tokens = r.json()
    claims = id_token.verify_oauth2_token(tokens["id_token"], g_requests.Request(), s.google_client_id)
    if not claims.get("email_verified"):
        raise HTTPException(403, "Google email is not verified")
    email = claims["email"].lower()

    if data["purpose"] == "drive":
        me = verify(request.cookies.get(COOKIE, ""))
        user = db.get(User, me["uid"]) if me and me.get("kind") == "session" else None
        if not user or user.email != email:
            raise HTTPException(403, "Drive must be connected with the account you are signed in as")
        refresh = tokens.get("refresh_token")
        if not refresh:
            raise HTTPException(400, "Google did not return a refresh token; try again")
        user.drive_refresh_token_enc = encrypt(refresh)
        if not db.scalar(select(Source).where(Source.owner_id == user.id, Source.kind == "drive")):
            db.add(Source(kind="drive", name="Google Drive", owner_id=user.id))
        db.commit()
        resp = RedirectResponse(f"{s.public_url}/sources")
    else:
        user = db.scalar(select(User).where(User.google_sub == claims["sub"])) or db.scalar(
            select(User).where(User.email == email)
        )
        if not user:
            user = User(email=email)
            db.add(user)
        user.google_sub, user.name, user.domain = claims["sub"], claims.get("name", ""), claims.get("hd")
        user.is_admin = user.is_admin or email in s.admin_email_set
        db.commit()
        resp = RedirectResponse(s.public_url)
        set_session(resp, user)
    resp.delete_cookie(STATE_COOKIE, path="/")
    return resp


class DevLogin(BaseModel):
    email: EmailStr
    name: str = ""


@router.post("/dev-login")
def dev_login(body: DevLogin, db: Session = Depends(get_db)):
    """Local-development login without Google. Disabled unless AUTH_DEV_MODE=true."""
    s = get_settings()
    if not s.auth_dev_mode:
        raise HTTPException(404)
    email = body.email.lower()
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        user = User(email=email, name=body.name)
        db.add(user)
    user.is_admin = user.is_admin or email in s.admin_email_set
    db.commit()
    from fastapi.responses import JSONResponse

    resp = JSONResponse({"email": user.email, "is_admin": user.is_admin})
    set_session(resp, user)
    return resp


@router.post("/logout")
def logout():
    from fastapi.responses import JSONResponse

    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_admin": user.is_admin,
        "drive_connected": bool(user.drive_refresh_token_enc),
    }
