import string
import random

from fastapi import HTTPException, status
from sqlalchemy import select, delete, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.team import Team
from app.models.transaction import Transaction
from app.models.chat_message import ChatMessage
from app.models.file_record import FileRecord
from app.models.transaction_proposal import TransactionProposal


def _generate_invite_code(length: int = 6) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


# ---- Permission helpers ----


async def verify_team_membership(
    db: AsyncSession, user_id: int, team_id: int
) -> User:
    """Verify the user belongs to the given team. Returns the user on success,
    raises 403 on failure."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this team",
        )
    return user


async def verify_team_admin(
    db: AsyncSession, user_id: int, team_id: int
) -> User:
    """Verify the user is an admin of the given team. Raises 403 if not a member
    or not an admin."""
    user = await verify_team_membership(db, user_id, team_id)
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team admins can perform this action",
        )
    return user


async def _count_team_admins(db: AsyncSession, team_id: int) -> int:
    """Count the number of admin members in a team."""
    count = await db.scalar(
        select(sa_func.count(User.id)).where(
            User.team_id == team_id,
            User.role == "admin",
        )
    )
    return count or 0


async def _ensure_not_last_admin(
    db: AsyncSession, user_id: int, team_id: int
) -> None:
    """Raise 400 if user_id is the last admin in the team."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.role != "admin":
        return  # Not an admin, no issue

    admin_count = await _count_team_admins(db, team_id)
    if admin_count <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove or demote the last admin of the team",
        )


# ---- Team CRUD ----


async def get_user_teams(db: AsyncSession, user_id: int) -> list[dict]:
    """Get all teams for the current user with their member lists."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.team_id is None:
        return []

    team_result = await db.execute(
        select(Team).where(Team.id == user.team_id)
    )
    team = team_result.scalar_one_or_none()
    if team is None:
        return []

    members_result = await db.execute(
        select(User).where(User.team_id == team.id)
    )
    members = members_result.scalars().all()

    return [
        {
            "id": team.id,
            "name": team.name,
            "invite_code": team.invite_code,
            "created_at": team.created_at.isoformat() if team.created_at else None,
            "members": [
                {
                    "id": m.id,
                    "name": m.name,
                    "role": m.role,
                    "phone": m.phone,
                    "open_id": m.open_id,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in members
            ],
        }
    ]


async def get_team(db: AsyncSession, team_id: int) -> dict:
    """Get a single team with its member list."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    members_result = await db.execute(
        select(User).where(User.team_id == team.id)
    )
    members = members_result.scalars().all()

    return {
        "id": team.id,
        "name": team.name,
        "invite_code": team.invite_code,
        "created_at": team.created_at.isoformat() if team.created_at else None,
        "members": [
            {
                "id": m.id,
                "name": m.name,
                "role": m.role,
                "phone": m.phone,
                "open_id": m.open_id,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in members
        ],
    }


async def create_team(
    db: AsyncSession, name: str, creator_user_id: int
) -> dict:
    """Create a new team. The creator is assigned as admin."""
    # Check if creator is already in a team
    result = await db.execute(select(User).where(User.id == creator_user_id))
    creator = result.scalar_one_or_none()
    if creator is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    invite_code = _generate_invite_code()
    team = Team(name=name, invite_code=invite_code)
    db.add(team)
    await db.flush()

    creator.team_id = team.id
    creator.role = "admin"
    await db.flush()

    return {
        "id": team.id,
        "name": team.name,
        "invite_code": team.invite_code,
        "created_at": team.created_at.isoformat() if team.created_at else None,
        "members": [
            {
                "id": creator.id,
                "name": creator.name,
                "role": creator.role,
                "phone": creator.phone,
                "open_id": creator.open_id,
                "created_at": creator.created_at.isoformat() if creator.created_at else None,
            }
        ],
    }


async def update_team(db: AsyncSession, team_id: int, name: str) -> dict:
    """Update a team's name."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    team.name = name
    await db.flush()

    return {
        "id": team.id,
        "name": team.name,
        "invite_code": team.invite_code,
        "created_at": team.created_at.isoformat() if team.created_at else None,
    }


async def delete_team(db: AsyncSession, team_id: int) -> None:
    """Delete a team and all associated data."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    # Cascade-clean associated data
    await db.execute(
        delete(Transaction).where(Transaction.team_id == team_id)
    )
    await db.execute(
        delete(ChatMessage).where(ChatMessage.team_id == team_id)
    )
    await db.execute(
        delete(FileRecord).where(FileRecord.team_id == team_id)
    )
    await db.execute(
        delete(TransactionProposal).where(TransactionProposal.team_id == team_id)
    )

    # Detach members
    await db.execute(
        User.__table__.update()
        .where(User.team_id == team_id)
        .values(team_id=None, role="member")
    )

    # Delete the team
    await db.delete(team)
    await db.flush()


async def regenerate_invite_code(db: AsyncSession, team_id: int) -> dict:
    """Regenerate the invite code for a team."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    team.invite_code = _generate_invite_code()
    await db.flush()

    return {
        "invite_code": team.invite_code,
    }


# ---- Member CRUD ----


async def get_team_members(db: AsyncSession, team_id: int) -> list[dict]:
    """List all members of a team."""
    # Verify team exists
    result = await db.execute(select(Team).where(Team.id == team_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    members_result = await db.execute(
        select(User).where(User.team_id == team_id)
    )
    members = members_result.scalars().all()

    return [
        {
            "id": m.id,
            "name": m.name,
            "role": m.role,
            "phone": m.phone,
            "open_id": m.open_id,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in members
    ]


async def add_member_to_team(
    db: AsyncSession, team_id: int, user_id: int
) -> dict:
    """Add a user to a team as a member."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.team_id = team_id
    user.role = "member"
    await db.flush()

    return {
        "id": user.id,
        "name": user.name,
        "role": user.role,
        "phone": user.phone,
        "open_id": user.open_id,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


async def update_member(
    db: AsyncSession,
    team_id: int,
    target_user_id: int,
    name: str | None = None,
    role: str | None = None,
) -> dict:
    """Update a team member's name and/or role."""
    result = await db.execute(
        select(User).where(User.id == target_user_id, User.team_id == team_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this team",
        )

    # If demoting from admin to member, check not last admin
    if role == "member" and user.role == "admin":
        await _ensure_not_last_admin(db, target_user_id, team_id)

    if name is not None:
        user.name = name
    if role is not None:
        user.role = role
    await db.flush()

    return {
        "id": user.id,
        "name": user.name,
        "role": user.role,
        "phone": user.phone,
        "open_id": user.open_id,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


async def remove_member(
    db: AsyncSession, team_id: int, target_user_id: int
) -> None:
    """Remove a user from a team."""
    result = await db.execute(
        select(User).where(User.id == target_user_id, User.team_id == team_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this team",
        )

    await _ensure_not_last_admin(db, target_user_id, team_id)

    user.team_id = None
    user.role = "member"
    await db.flush()


# ---- Join team ----


async def join_team_by_invite(db: AsyncSession, user_id: int, invite_code: str) -> dict:
    """Join a team using its invite code."""
    result = await db.execute(
        select(Team).where(Team.invite_code == invite_code)
    )
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid invite code",
        )

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.team_id = team.id
    user.role = "member"
    await db.flush()

    return {
        "team_id": team.id,
        "team_name": team.name,
        "user_id": user.id,
        "role": user.role,
    }
