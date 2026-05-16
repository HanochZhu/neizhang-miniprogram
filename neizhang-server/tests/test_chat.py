"""对话流式接口：通过 mock 流避免真实调用大模型。"""

import json
import uuid

from app.services.chat_service import (
    _confirmation_sse_from_propose,
    _extra_events_after_tool,
)
from app.tools.finance_tools import propose_transaction


def _login(client):
    phone = f"137{uuid.uuid4().int % 10**8:08d}"
    r = client.post(
        "/api/v1/auth/phone-login",
        json={"phone": phone, "name": "对话测试"},
    )
    assert r.status_code == 200
    return r.json()["token"]


async def _fake_chat_stream(team_id, user_id, user_message, db):
    yield 'data: {"type":"text_delta","content":"测试回复"}\n\n'
    yield 'data: {"type":"message_stop"}\n\n'


def test_chat_send_requires_auth(client):
    r = client.post("/api/v1/chat/send", json={"message": "你好"})
    assert r.status_code == 401


def test_chat_send_rejects_empty_message(client):
    token = _login(client)
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
    token = _login(client)
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


def test_chat_send_streams_when_mocked(client, monkeypatch):
    import app.routers.chat as chat_mod

    monkeypatch.setattr(chat_mod, "chat_stream", _fake_chat_stream)

    token = _login(client)
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
