"""管理后台页面与 JSON 接口（当前无鉴权）。"""


def test_admin_html_dashboard(client):
    r = client.get("/admin")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "内账" in r.text


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
