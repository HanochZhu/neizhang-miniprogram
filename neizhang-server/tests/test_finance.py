"""财务汇总等需登录的接口。"""

import uuid


def _phone_login(client):
    phone = f"139{uuid.uuid4().int % 10**8:08d}"
    r = client.post(
        "/api/v1/auth/phone-login",
        json={"phone": phone, "name": "财务测试"},
    )
    assert r.status_code == 200
    return r.json()["token"]


def test_finance_summary_requires_auth(client):
    r = client.get("/api/v1/finance/summary")
    assert r.status_code == 401


def test_finance_summary_with_token(client):
    token = _phone_login(client)
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


def test_finance_summary_invalid_date(client):
    token = _phone_login(client)
    r = client.get(
        "/api/v1/finance/summary",
        params={"start_date": "not-a-date"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
