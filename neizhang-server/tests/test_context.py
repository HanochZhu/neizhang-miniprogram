"""聊天上下文：读库去重、避免重复写入。"""

import asyncio
import uuid

from sqlalchemy import select, func as sa_func

from app.database import async_session_factory
from app.models.chat_message import ChatMessage
from app.services.chat_service import _save_message
from app.services.context_service import (
    append_user_message,
    deduplicate_messages,
    get_recent_messages,
    is_duplicate_of_last_message,
)


def test_deduplicate_messages():
    raw = [
        {"role": "user", "content": "你好"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "在"},
    ]
    assert len(deduplicate_messages(raw)) == 2


def test_append_user_message_skips_duplicate_tail():
    history = [{"role": "user", "content": "午餐50"}]
    assert append_user_message(history, "午餐50") == history
    assert len(append_user_message(history, "晚餐30")) == 2


def test_save_message_skips_without_force(client):
    r = client.post(
        "/api/v1/auth/phone-login",
        json={"phone": f"138{uuid.uuid4().int % 10**8:08d}", "name": "去重"},
    )
    team_id, user_id = r.json()["team_id"], r.json()["user_id"]

    async def _run():
        async with async_session_factory() as db:
            await _save_message(db, team_id, user_id, "user", "同一条")
            await _save_message(db, team_id, user_id, "user", "同一条")
            await db.commit()

    asyncio.run(_run())

    async def _count():
        async with async_session_factory() as db:
            return await db.scalar(
                select(sa_func.count(ChatMessage.id)).where(
                    ChatMessage.team_id == team_id,
                    ChatMessage.content == "同一条",
                )
            )

    assert asyncio.run(_count()) == 1


def test_save_message_force_writes_duplicate(client):
    r = client.post(
        "/api/v1/auth/phone-login",
        json={"phone": f"136{uuid.uuid4().int % 10**8:08d}", "name": "强制保存"},
    )
    team_id, user_id = r.json()["team_id"], r.json()["user_id"]

    async def _run():
        async with async_session_factory() as db:
            await _save_message(db, team_id, user_id, "user", "同一条")
            await _save_message(db, team_id, user_id, "user", "同一条", force=True)
            await db.commit()

    asyncio.run(_run())

    async def _count():
        async with async_session_factory() as db:
            return await db.scalar(
                select(sa_func.count(ChatMessage.id)).where(
                    ChatMessage.team_id == team_id,
                    ChatMessage.content == "同一条",
                )
            )

    assert asyncio.run(_count()) == 2


def test_is_duplicate_of_last_message(client):
    r = client.post(
        "/api/v1/auth/phone-login",
        json={"phone": f"134{uuid.uuid4().int % 10**8:08d}", "name": "重复检测"},
    )
    team_id, user_id = r.json()["team_id"], r.json()["user_id"]

    async def _run():
        async with async_session_factory() as db:
            await _save_message(db, team_id, user_id, "user", "hello")
            assert await is_duplicate_of_last_message(team_id, "user", "hello", db)
            assert not await is_duplicate_of_last_message(team_id, "user", "other", db)
            await db.commit()

    asyncio.run(_run())


def test_get_recent_messages_empty_when_load_history_disabled(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "chat_load_history", False)
    r = client.post(
        "/api/v1/auth/phone-login",
        json={"phone": f"133{uuid.uuid4().int % 10**8:08d}", "name": "无历史"},
    )
    team_id, user_id = r.json()["team_id"], r.json()["user_id"]

    async def _insert():
        async with async_session_factory() as db:
            db.add(
                ChatMessage(
                    team_id=team_id,
                    user_id=user_id,
                    role="user",
                    content="不应出现在上下文",
                )
            )
            await db.commit()

    asyncio.run(_insert())

    async def _load():
        async with async_session_factory() as db:
            return await get_recent_messages(team_id, db)

    assert asyncio.run(_load()) == []


def test_get_recent_messages_deduped(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "chat_load_history", True)
    r = client.post(
        "/api/v1/auth/phone-login",
        json={"phone": f"137{uuid.uuid4().int % 10**8:08d}", "name": "历史"},
    )
    team_id, user_id = r.json()["team_id"], r.json()["user_id"]

    async def _insert():
        async with async_session_factory() as db:
            for _ in range(2):
                db.add(
                    ChatMessage(
                        team_id=team_id,
                        user_id=user_id,
                        role="assistant",
                        content="重复回复",
                    )
                )
            await db.commit()

    asyncio.run(_insert())

    async def _load():
        async with async_session_factory() as db:
            return await get_recent_messages(team_id, db)

    msgs = asyncio.run(_load())
    dup = [m for m in msgs if m["content"] == "重复回复"]
    assert len(dup) == 1
