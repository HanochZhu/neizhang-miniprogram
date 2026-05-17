import string
import random
from datetime import datetime, timedelta, timezone

from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.models.team import Team


def _generate_invite_code(length: int = 6) -> str:
    """Generate a random alphanumeric invite code."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


async def get_or_create_user_by_openid(db: AsyncSession, open_id: str) -> User:
    """Find user by open_id or create a new one."""
    result = await db.execute(select(User).where(User.open_id == open_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            open_id=open_id,
            name="",
            role="member",
        )
        db.add(user)
        await db.flush()

        # Create a default team for the new user (creator becomes admin)
        await create_default_team(db, creator_user_id=user.id)

    return user


async def get_or_create_user_by_phone(db: AsyncSession, phone: str, name: str) -> User:
    """Find user by phone or create a new one."""
    result = await db.execute(select(User).where(User.phone == phone))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            phone=phone,
            name=name,
            role="member",
        )
        db.add(user)
        await db.flush()

        # Create a default team for the new user (creator becomes admin)
        await create_default_team(db, creator_user_id=user.id)
    else:
        # Update name if provided
        if name:
            user.name = name
            await db.flush()

    return user


async def create_default_team(db: AsyncSession, creator_user_id: int | None = None) -> Team:
    """Create a new team with a random invite code.

    If creator_user_id is provided, assign the team to that user and set their
    role to "admin".
    """
    invite_code = _generate_invite_code()
    team = Team(
        name="默认团队",
        invite_code=invite_code,
    )
    db.add(team)
    await db.flush()

    if creator_user_id is not None:
        result = await db.execute(select(User).where(User.id == creator_user_id))
        user = result.scalar_one_or_none()
        if user is not None:
            user.team_id = team.id
            user.role = "admin"
            await db.flush()

    return team


def create_token(data: dict) -> str:
    """Create a JWT token with expiration."""
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    payload["exp"] = expire
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Returns the payload dict or raises JWTError."""
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    return payload
