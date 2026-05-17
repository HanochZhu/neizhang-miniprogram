"""对话流式接口：通过 mock 流避免真实调用大模型。"""

import asyncio
import json
import uuid

from sqlalchemy import select

from app.database import stream_with_db
from app.models.transaction import Transaction
from app.services.chat_service import (
    _confirmation_sse_from_propose,
    _extra_events_after_tool,
)
from app.tools.finance_tools import add_transaction, propose_transaction


def _login(client):
    phone = f"137{uuid.uuid4().int % 10**8:08d}"
    r = client.post(
        "/api/v1/auth/phone-login",
        json={"phone": phone, "name": "对话测试"},
    )
    assert r.status_code == 200
    data = r.json()
    return data["token"], data["user_id"], data["team_id"]


async def _fake_chat_stream(team_id, user_id, user_message, db, **kwargs):
    yield 'data: {"type":"text_delta","content":"测试回复"}\n\n'
    yield 'data: {"type":"message_stop"}\n\n'


def test_chat_send_requires_auth(client):
    r = client.post("/api/v1/chat/send", json={"message": "你好"})
    assert r.status_code == 401


def test_chat_send_rejects_empty_message(client):
    token, _, _ = _login(client)
    r = client.post(
        "/api/v1/chat/send",
        json={"message": "   "},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_extra_events_after_add_transaction_success():
    result = json.dumps(
        {"success": True, "message": "已记录支出：¥10.00，类别：餐饮"},
        ensure_ascii=False,
    )
    events = _extra_events_after_tool("add_transaction", result)
    types = [e["type"] for e in events]
    assert "record_success" in types
    assert "text_delta" in types
    assert any("已记录支出" in e.get("content", "") for e in events)


def test_extra_events_after_add_transaction_error():
    result = json.dumps({"error": "金额必须大于0"}, ensure_ascii=False)
    assert _extra_events_after_tool("add_transaction", result) == []


def test_extra_events_after_propose_transaction():
    result = json.dumps(
        {
            "success": True,
            "pending": True,
            "proposal_id": "abc-123",
            "message": "请确认是否保存：支出 ¥50.00，类别：餐饮",
            "reason": "金额来自推测",
            "transaction": {
                "type": "expense",
                "amount": 50,
                "category": "餐饮",
            },
        },
        ensure_ascii=False,
    )
    events = _extra_events_after_tool("propose_transaction", result)
    types = [e["type"] for e in events]
    assert "confirmation_required" in types
    confirm = next(e for e in events if e["type"] == "confirmation_required")
    assert confirm["proposal_id"] == "abc-123"
    assert confirm["transaction"]["amount"] == 50


def test_confirmation_sse_from_propose_invalid():
    assert _confirmation_sse_from_propose('{"error":"x"}') is None


def test_propose_transaction_rejects_invalid_amount():
    import asyncio

    async def _run():
        return await propose_transaction(
            team_id=1,
            user_id=1,
            tx_type="expense",
            amount=0,
            category="交通",
            reason="测试",
            db=None,
        )

    result = asyncio.run(_run())
    data = json.loads(result)
    assert "error" in data


def test_chat_confirm_unknown_proposal_streams_error(client):
    token, _, _ = _login(client)
    with client.stream(
        "POST",
        "/api/v1/chat/confirm",
        json={"proposal_id": "non-existent-id", "confirmed": True},
        headers={"Authorization": f"Bearer {token}"},
    ) as r:
        assert r.status_code == 200
        body = "".join(chunk.decode("utf-8") for chunk in r.iter_bytes())
    assert "error" in body
    assert "message_stop" in body


def test_chat_confirm_requires_auth(client):
    r = client.post(
        "/api/v1/chat/confirm",
        json={"proposal_id": "x", "confirmed": True},
    )
    assert r.status_code == 401


def test_stream_with_db_commits_writes(client):
    """流式接口应在流结束后提交数据库写入。"""
    _, user_id, team_id = _login(client)
    amount = 88.5 + (uuid.uuid4().int % 1000) / 100.0

    async def _run():
        async def _factory(db):
            result = await add_transaction(
                team_id=team_id,
                user_id=user_id,
                tx_type="expense",
                amount=amount,
                category="测试",
                db=db,
            )
            assert json.loads(result)["success"]
            yield 'data: {"type":"message_stop"}\n\n'

        body = []
        async for chunk in stream_with_db(_factory):
            body.append(chunk)

        assert "message_stop" in "".join(body)

        from app.database import async_session_factory

        async with async_session_factory() as db:
            rows = await db.execute(
                select(Transaction).where(
                    Transaction.team_id == team_id,
                    Transaction.amount == amount,
                )
            )
            assert rows.scalar_one_or_none() is not None

    asyncio.run(_run())


def test_chat_send_duplicate_message_requires_confirm(client, monkeypatch):
    import app.services.chat_service as chat_svc

    called = {"chat": False}

    async def _fake(*args, **kwargs):
        called["chat"] = True
        async for c in _fake_chat_stream(*args, **kwargs):
            yield c

    async def _is_dup(*args, **kwargs):
        return True

    monkeypatch.setattr(chat_svc, "chat_stream", _fake)
    monkeypatch.setattr(chat_svc, "is_duplicate_of_last_message", _is_dup)

    token, _, _ = _login(client)
    with client.stream(
        "POST",
        "/api/v1/chat/send",
        json={"message": "dup-msg"},
        headers={"Authorization": f"Bearer {token}"},
    ) as r:
        assert r.status_code == 200
        body = "".join(chunk.decode("utf-8") for chunk in r.iter_bytes())

    assert "duplicate_message_required" in body
    assert "message_stop" in body
    assert called["chat"] is False


def test_confirm_duplicate_cancelled(client):
    token, _, _ = _login(client)
    with client.stream(
        "POST",
        "/api/v1/chat/confirm-duplicate",
        json={"message": "任意", "confirmed": False},
        headers={"Authorization": f"Bearer {token}"},
    ) as r:
        body = "".join(chunk.decode("utf-8") for chunk in r.iter_bytes())
    assert "duplicate_message_cancelled" in body
    assert "message_stop" in body


def test_confirm_duplicate_confirmed_streams_chat(client, monkeypatch):
    import app.services.chat_service as chat_svc

    monkeypatch.setattr(chat_svc, "chat_stream", _fake_chat_stream)

    token, _, _ = _login(client)
    with client.stream(
        "POST",
        "/api/v1/chat/confirm-duplicate",
        json={"message": "继续对话", "confirmed": True},
        headers={"Authorization": f"Bearer {token}"},
    ) as r:
        body = "".join(chunk.decode("utf-8") for chunk in r.iter_bytes())
    assert "duplicate_message_confirmed" in body
    assert "text_delta" in body
    assert "message_stop" in body


def test_chat_send_streams_when_mocked(client, monkeypatch):
    import app.routers.chat as chat_mod

    monkeypatch.setattr(chat_mod, "chat_stream", _fake_chat_stream)

    token, _, _ = _login(client)
    with client.stream(
        "POST",
        "/api/v1/chat/send",
        json={"message": "记一笔"},
        headers={"Authorization": f"Bearer {token}"},
    ) as r:
        assert r.status_code == 200
        body = "".join(chunk.decode("utf-8") for chunk in r.iter_bytes())
    assert "text_delta" in body
    assert "message_stop" in body
