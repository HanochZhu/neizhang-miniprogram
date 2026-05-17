"""财务汇总等需登录的接口。"""

import asyncio
import uuid
from datetime import datetime

from app.database import async_session_factory
from app.models.transaction import Transaction


def _phone_login(client):
    phone = f"139{uuid.uuid4().int % 10**8:08d}"
    r = client.post(
        "/api/v1/auth/phone-login",
        json={"phone": phone, "name": "财务测试"},
    )
    assert r.status_code == 200
    data = r.json()
    return data["token"], data["user_id"], data["team_id"]


def test_finance_summary_requires_auth(client):
    r = client.get("/api/v1/finance/summary")
    assert r.status_code == 401


def test_finance_summary_includes_transaction_on_same_day(client):
    token, user_id, team_id = _phone_login(client)
    amount = 66.6 + (uuid.uuid4().int % 100)

    async def _insert():
        async with async_session_factory() as db:
            db.add(
                Transaction(
                    team_id=team_id,
                    user_id=user_id,
                    type="expense",
                    amount=amount,
                    category="测试",
                    transaction_date=datetime.now(),
                )
            )
            await db.commit()

    asyncio.run(_insert())

    today = datetime.now().strftime("%Y-%m-%d")
    r = client.get(
        "/api/v1/finance/summary",
        params={"scope": "team", "start_date": today, "end_date": today},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["expense_total"] >= amount
    assert data["transaction_count"] >= 1


def test_finance_summary_with_token(client):
    token, _, _ = _phone_login(client)
    r = client.get(
        "/api/v1/finance/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["income_total"] == 0.0
    assert data["expense_total"] == 0.0
    assert data["balance"] == 0.0
    assert data["transaction_count"] == 0
    assert data["by_category"] == []
    assert data["transactions"] == []


def test_finance_summary_respects_tx_limit(client):
    token, user_id, team_id = _phone_login(client)
    today = datetime.now().strftime("%Y-%m-%d")

    async def _insert_many():
        async with async_session_factory() as db:
            for i in range(25):
                db.add(
                    Transaction(
                        team_id=team_id,
                        user_id=user_id,
                        type="expense",
                        amount=10.0 + i,
                        category="测试",
                        transaction_date=datetime.now(),
                    )
                )
            await db.commit()

    asyncio.run(_insert_many())

    r = client.get(
        "/api/v1/finance/summary",
        params={
            "scope": "team",
            "start_date": today,
            "end_date": today,
            "tx_limit": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["transaction_count"] >= 25
    assert data["transactions_returned"] == 10
    assert len(data["transactions"]) == 10


def test_finance_summary_invalid_date(client):
    token, _, _ = _phone_login(client)
    r = client.get(
        "/api/v1/finance/summary",
        params={"start_date": "not-a-date"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
