from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.routers.auth import get_current_user
from app.database import stream_with_db
from app.services.chat_service import chat_stream, confirm_proposal_stream
from app.services.image_analysis_service import analyze_image_stream

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


class ConfirmRequest(BaseModel):
    proposal_id: str
    confirmed: bool = True


class AnalyzeImageRequest(BaseModel):
    file_id: int


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

    async def _factory(db):
        async for chunk in chat_stream(
            team_id=team_id,
            user_id=user_id,
            user_message=request.message.strip(),
            db=db,
        ):
            yield chunk

    return StreamingResponse(
        stream_with_db(_factory),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


@router.post("/confirm")
async def confirm_proposal(
    request: ConfirmRequest,
    current_user: dict = Depends(get_current_user),
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

    proposal_id = request.proposal_id.strip()

    async def _factory(db):
        async for chunk in confirm_proposal_stream(
            proposal_id=proposal_id,
            confirmed=request.confirmed,
            team_id=team_id,
            user_id=user_id,
            db=db,
        ):
            yield chunk

    return StreamingResponse(
        stream_with_db(_factory),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


@router.post("/analyze-image")
async def analyze_image(
    request: AnalyzeImageRequest,
    current_user: dict = Depends(get_current_user),
):
    """识别支付/收款截图，生成待确认记账提案（SSE）。"""
    user_id = current_user.get("user_id")
    team_id = current_user.get("team_id")

    if not user_id or not team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User or team not found. Please login first.",
        )

    if request.file_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file_id is required",
        )

    file_id = request.file_id

    async def _factory(db):
        async for chunk in analyze_image_stream(
            file_id=file_id,
            team_id=team_id,
            user_id=user_id,
            db=db,
        ):
            yield chunk

    return StreamingResponse(
        stream_with_db(_factory),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )
