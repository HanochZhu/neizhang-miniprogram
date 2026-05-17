from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.auth import get_current_user
from app.services.team_service import (
    get_user_teams,
    get_team,
    create_team,
    update_team,
    delete_team,
    regenerate_invite_code,
    get_team_members,
    add_member_to_team,
    update_member,
    remove_member,
    join_team_by_invite,
    verify_team_membership,
    verify_team_admin,
)

router = APIRouter(prefix="/api/v1/teams", tags=["teams"])


# ---- Pydantic models ----


class TeamMemberResponse(BaseModel):
    id: int
    name: str
    role: str
    phone: str | None = None
    open_id: str | None = None
    created_at: str | None = None


class TeamResponse(BaseModel):
    id: int
    name: str
    invite_code: str
    created_at: str | None = None
    members: list[TeamMemberResponse] = []


class TeamListResponse(BaseModel):
    teams: list[TeamResponse]


class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class UpdateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class AddMemberRequest(BaseModel):
    user_id: int


class UpdateMemberRequest(BaseModel):
    name: str | None = Field(default=None, max_length=50)
    role: str | None = Field(default=None, pattern="^(admin|member)$")


class JoinTeamRequest(BaseModel):
    invite_code: str = Field(..., min_length=1, max_length=20)


class InviteCodeResponse(BaseModel):
    invite_code: str


class JoinTeamResponse(BaseModel):
    team_id: int
    team_name: str
    user_id: int
    role: str


class MessageResponse(BaseModel):
    message: str


# ---- Team endpoints ----


@router.get("", response_model=list[TeamResponse])
async def list_teams(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all teams the current user belongs to."""
    teams = await get_user_teams(db, current_user["user_id"])
    return teams


@router.get("/{team_id}", response_model=TeamResponse)
async def view_team(
    team_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get team details. User must be a member of the team."""
    await verify_team_membership(db, current_user["user_id"], team_id)
    return await get_team(db, team_id)


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_new_team(
    request: CreateTeamRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new team. The creator becomes the team admin."""
    return await create_team(db, request.name, current_user["user_id"])


@router.put("/{team_id}", response_model=TeamResponse)
async def update_team_name(
    team_id: int,
    request: UpdateTeamRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update team name. Only admins can do this."""
    await verify_team_admin(db, current_user["user_id"], team_id)
    return await update_team(db, team_id, request.name)


@router.delete("/{team_id}", response_model=MessageResponse)
async def delete_team_endpoint(
    team_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a team and all associated data. Only admins can do this."""
    await verify_team_admin(db, current_user["user_id"], team_id)
    await delete_team(db, team_id)
    return MessageResponse(message="Team deleted successfully")


@router.post("/{team_id}/regenerate-code", response_model=InviteCodeResponse)
async def regenerate_team_code(
    team_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate the team invite code. Only admins can do this."""
    await verify_team_admin(db, current_user["user_id"], team_id)
    return await regenerate_invite_code(db, team_id)


# ---- Member endpoints ----


@router.get("/{team_id}/members", response_model=list[TeamMemberResponse])
async def list_members(
    team_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all members of a team. User must be a team member."""
    await verify_team_membership(db, current_user["user_id"], team_id)
    return await get_team_members(db, team_id)


@router.post("/{team_id}/members", response_model=TeamMemberResponse, status_code=status.HTTP_201_CREATED)
async def add_member(
    team_id: int,
    request: AddMemberRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a user to the team. Only admins can do this."""
    await verify_team_admin(db, current_user["user_id"], team_id)
    return await add_member_to_team(db, team_id, request.user_id)


@router.put("/{team_id}/members/{user_id}", response_model=TeamMemberResponse)
async def update_member_endpoint(
    team_id: int,
    user_id: int,
    request: UpdateMemberRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a member's name or role. Only admins can do this."""
    await verify_team_admin(db, current_user["user_id"], team_id)
    return await update_member(db, team_id, user_id, request.name, request.role)


@router.delete("/{team_id}/members/{user_id}", response_model=MessageResponse)
async def remove_member_endpoint(
    team_id: int,
    user_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from the team. Only admins can do this."""
    await verify_team_admin(db, current_user["user_id"], team_id)
    await remove_member(db, team_id, user_id)
    return MessageResponse(message="Member removed successfully")


# ---- Join team ----


@router.post("/join", response_model=JoinTeamResponse)
async def join_team(
    request: JoinTeamRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Join a team using its invite code."""
    return await join_team_by_invite(db, current_user["user_id"], request.invite_code)
