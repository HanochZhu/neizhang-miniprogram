"""图片识别记账流程测试。"""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.database import async_session_factory
from app.models.file_record import FileRecord
from app.models.transaction_proposal import TransactionProposal
from app.services.image_analysis_service import (
    _extract_json,
    _is_image_file,
    analyze_image_stream,
)


def test_extract_json_from_markdown_fence():
    raw = '说明\n```json\n{"is_financial": true, "amount": 10}\n```'
    data = _extract_json(raw)
    assert data.get("is_financial") is True
    assert data.get("amount") == 10


def test_is_image_file():
    assert _is_image_file("pay.png")
    assert not _is_image_file("doc.pdf")


def test_analyze_image_stream_creates_proposal(client, tmp_path, monkeypatch):
    import asyncio

    from tests.test_chat import _login

    _login(client)
    # get user/team from fresh login
    phone = f"136{uuid.uuid4().int % 10**8:08d}"
    r = client.post(
        "/api/v1/auth/phone-login",
        json={"phone": phone, "name": "图片测试"},
    )
    user_id = r.json()["user_id"]
    team_id = r.json()["team_id"]
    img_path = tmp_path / "receipt.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    async def _insert_file():
        async with async_session_factory() as db:
            record = FileRecord(
                team_id=team_id,
                user_id=user_id,
                filename="receipt.png",
                storage_path=str(img_path),
                url="/static/receipt.png",
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)
            return record.id

    file_id = asyncio.run(_insert_file())

    vision_result = {
        "is_financial": True,
        "type": "expense",
        "amount": 88.0,
        "category": "餐饮",
        "description": "午餐",
        "transaction_date": "2025-05-17",
        "summary": "识别到微信支付支出",
        "reason": "微信支付截图，金额¥88.00",
    }

    async def _fake_vision(*args, **kwargs):
        return vision_result

    chunks = []

    async def _run():
        from app.database import stream_with_db

        async def factory(db):
            async for c in analyze_image_stream(file_id, team_id, user_id, db):
                chunks.append(c)
                yield c

        async for _ in stream_with_db(factory):
            pass

    with patch(
        "app.services.image_analysis_service._call_vision_api",
        new=AsyncMock(side_effect=_fake_vision),
    ):
        asyncio.run(_run())

    body = "".join(chunks)
    assert "confirmation_required" in body
    assert "proposal_id" in body

    async def _check():
        async with async_session_factory() as db:
            rows = await db.execute(
                select(TransactionProposal).where(TransactionProposal.team_id == team_id)
            )
            proposals = rows.scalars().all()
            assert len(proposals) >= 1
            assert proposals[-1].amount == 88.0
            assert proposals[-1].status == "pending"

    asyncio.run(_check())
