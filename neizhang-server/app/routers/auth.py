import httpx
from fastapi import APIRouter, Depends, HTTPException, Header, status
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User as UserModel
from app.services.auth_service import (
    get_or_create_user_by_openid,
    get_or_create_user_by_phone,
    decode_token,
    create_token,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    code: str


class PhoneLoginRequest(BaseModel):
    phone: str
    name: str


class LoginResponse(BaseModel):
    token: str
    user_id: int
    team_id: int
    open_id: str = ""
    is_new_user: bool = False


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login or register via WeChat code (wx.login)."""
    # Exchange code for open_id via WeChat API
    url = (
        f"https://api.weixin.qq.com/sns/jscode2session"
        f"?appid={settings.wechat_app_id}"
        f"&secret={settings.wechat_app_secret}"
        f"&js_code={request.code}"
        f"&grant_type=authorization_code"
    )

    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        data = resp.json()

    if "openid" not in data:
        error_msg = data.get("errmsg", "WeChat login failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"WeChat authentication failed: {error_msg}",
        )

    open_id = data["openid"]

    # Find or create user
    user = await get_or_create_user_by_openid(db, open_id)

    # Determine if this is a new user (no name set)
    is_new = not bool(user.name)

    # Generate JWT
    token = create_token(
        {
            "user_id": user.id,
            "team_id": user.team_id or 0,
            "open_id": open_id,
        }
    )

    return LoginResponse(
        token=token,
        user_id=user.id,
        team_id=user.team_id or 0,
        open_id=open_id,
        is_new_user=is_new,
    )


@router.post("/phone-login", response_model=LoginResponse)
async def phone_login(request: PhoneLoginRequest, db: AsyncSession = Depends(get_db)):
    """Login or register via phone number."""
    user = await get_or_create_user_by_phone(db, request.phone, request.name)

    # Check if just created by seeing if there's only one record
    result = await db.execute(
        select(UserModel).where(UserModel.phone == request.phone)
    )
    users = result.scalars().all()
    is_new = len(users) <= 1 and user.name == request.name

    token = create_token(
        {
            "user_id": user.id,
            "team_id": user.team_id or 0,
            "phone": request.phone,
        }
    )

    return LoginResponse(
        token=token,
        user_id=user.id,
        team_id=user.team_id or 0,
        is_new_user=is_new,
    )


# ---- Dependency for protected routes ----


async def get_current_user(
    authorization: str = Header(None),
) -> dict:
    """FastAPI dependency that extracts and validates the JWT from the Authorization header.

    Expected format: "Bearer <token>"
    Returns the decoded token payload dict.
    Raises 401 if missing or invalid.
    """
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload
