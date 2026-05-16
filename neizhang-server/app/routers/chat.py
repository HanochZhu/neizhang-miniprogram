from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.auth import get_current_user
from app.services.chat_service import chat_stream, confirm_proposal_stream

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


class ConfirmRequest(BaseModel):
    proposal_id: str
    confirmed: bool = True


def _sse_headers() -> dict:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


@router.post("/send")
async def send_message(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a chat message and stream the AI response via SSE."""
    user_id = current_user.get("user_id")
    team_id = current_user.get("team_id")

    if not user_id or not team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User or team not found. Please login first.",
        )

    if not request.message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message cannot be empty",
        )

    return StreamingResponse(
        chat_stream(
            team_id=team_id,
            user_id=user_id,
            user_message=request.message.strip(),
            db=db,
        ),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


@router.post("/confirm")
async def confirm_proposal(
    request: ConfirmRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """用户确认或取消待记账提案，流式返回处理结果。"""
    user_id = current_user.get("user_id")
    team_id = current_user.get("team_id")

    if not user_id or not team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User or team not found. Please login first.",
        )

    if not request.proposal_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="proposal_id is required",
        )

    return StreamingResponse(
        confirm_proposal_stream(
            proposal_id=request.proposal_id.strip(),
            confirmed=request.confirmed,
            team_id=team_id,
            user_id=user_id,
            db=db,
        ),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )
