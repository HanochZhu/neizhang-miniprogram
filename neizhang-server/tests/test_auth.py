"""登录与鉴权相关用例。"""

import uuid


def test_phone_login_creates_user_and_token(client):
    phone = f"138{uuid.uuid4().int % 10**8:08d}"
    r = client.post(
        "/api/v1/auth/phone-login",
        json={"phone": phone, "name": "测试用户"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "token" in data
    assert data["user_id"] >= 1
    assert data["team_id"] >= 1
    assert isinstance(data["token"], str) and len(data["token"]) > 20


def test_wechat_login_uses_openid_from_wechat(client, monkeypatch):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            class Resp:
                def json(self):
                    return {"openid": f"wx-{uuid.uuid4().hex[:16]}"}

            return Resp()

    import app.routers.auth as auth_mod

    monkeypatch.setattr(auth_mod.httpx, "AsyncClient", lambda *a, **k: FakeClient())

    r = client.post("/api/v1/auth/login", json={"code": "mock-js-code"})
    assert r.status_code == 200
    data = r.json()
    assert data["open_id"].startswith("wx-")
    assert data["token"]


def test_wechat_login_fails_without_openid(client, monkeypatch):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            class Resp:
                def json(self):
                    return {"errcode": 40029, "errmsg": "invalid code"}

            return Resp()

    import app.routers.auth as auth_mod

    monkeypatch.setattr(auth_mod.httpx, "AsyncClient", lambda *a, **k: FakeClient())

    r = client.post("/api/v1/auth/login", json={"code": "bad-code"})
    assert r.status_code == 401
    assert "WeChat" in r.json()["detail"] or "authentication" in r.json()["detail"].lower()
