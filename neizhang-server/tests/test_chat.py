"""对话流式接口：通过 mock 流避免真实调用大模型。"""

import uuid


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
