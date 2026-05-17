"""管理后台页面与 JSON 接口（当前无鉴权）。"""

import asyncio
import uuid
from datetime import datetime

from app.database import async_session_factory
from app.models.transaction import Transaction


def _phone_login(client):
    phone = f"139{uuid.uuid4().int % 10**8:08d}"
    r = client.post(
        "/api/v1/auth/phone-login",
        json={"phone": phone, "name": "管理后台测试"},
    )
    assert r.status_code == 200
    data = r.json()
    return data["user_id"], data["team_id"]


def test_admin_html_dashboard(client):
    r = client.get("/admin")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "内账" in r.text
    assert "团队管理" in r.text
    assert "系统概览" in r.text
    assert "快捷入口" in r.text


def test_admin_stats_json(client):
    r = client.get("/admin/api/v1/admin/stats")
    assert r.status_code == 200
    data = r.json()
    for key in (
        "user_count",
        "team_count",
        "transaction_count",
        "chat_message_count",
        "file_count",
    ):
        assert key in data
        assert isinstance(data[key], int)


def test_admin_teams_json(client):
    _phone_login(client)
    r = client.get("/admin/api/v1/admin/teams")
    assert r.status_code == 200
    data = r.json()
    assert "teams" in data
    assert len(data["teams"]) >= 1
    team = data["teams"][0]
    for key in (
        "id",
        "name",
        "invite_code",
        "member_count",
        "transaction_count",
        "created_at",
    ):
        assert key in team


def test_admin_transactions_table_scrollable_over_20(client):
    user_id, team_id = _phone_login(client)

    async def _insert_many():
        async with async_session_factory() as db:
            for i in range(21):
                db.add(
                    Transaction(
                        team_id=team_id,
                        user_id=user_id,
                        type="expense",
                        amount=1.0 + i,
                        category="管理后台测试",
                        transaction_date=datetime.now(),
                    )
                )
            await db.commit()

    asyncio.run(_insert_many())

    r = client.get("/admin/transactions")
    assert r.status_code == 200
    assert "table-wrap scrollable" in r.text
    assert "管理后台测试" in r.text
