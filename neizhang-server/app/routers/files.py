import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.file_record import FileRecord
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/v1/files", tags=["files"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file and save a record in the database."""
    user_id = current_user.get("user_id")
    team_id = current_user.get("team_id")

    if not user_id or not team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User or team not found",
        )

    # Validate file
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    # Create upload directory if it doesn't exist
    upload_dir = settings.upload_dir
    os.makedirs(upload_dir, exist_ok=True)

    # Generate unique filename to avoid collisions
    ext = os.path.splitext(file.filename)[1] or ""
    unique_name = f"{uuid.uuid4().hex}{ext}"
    storage_path = os.path.join(upload_dir, unique_name)

    # Save file
    content = await file.read()
    try:
        with open(storage_path, "wb") as f:
            f.write(content)
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save file: {str(e)}",
        )

    # Build URL (relative path for now)
    url = f"/static/{unique_name}"

    # Save record to database
    file_record = FileRecord(
        team_id=team_id,
        user_id=user_id,
        filename=file.filename,
        storage_path=storage_path,
        url=url,
    )
    db.add(file_record)
    await db.flush()

    return {
        "id": file_record.id,
        "filename": file.filename,
        "url": url,
        "size": len(content),
    }
