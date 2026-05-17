import string
import random

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func as sa_func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.team import Team
from app.models.transaction import Transaction
from app.models.chat_message import ChatMessage
from app.models.file_record import FileRecord
from app.models.transaction_proposal import TransactionProposal

router = APIRouter(prefix="/admin", tags=["admin"])

SCROLL_TABLE_THRESHOLD = 20

ADMIN_STYLES = r"""
    :root {
        --bg: #f0f2f5;
        --surface: #ffffff;
        --primary: #4f6ef7;
        --primary-light: #eef0ff;
        --text: #1a1a2e;
        --text-secondary: #6b7280;
        --border: #e5e7eb;
        --success: #10b981;
        --success-bg: #ecfdf5;
        --danger: #ef4444;
        --danger-bg: #fef2f2;
        --warning: #f59e0b;
        --warning-bg: #fffbeb;
        --sidebar-w: 220px;
        --radius: 10px;
    }

    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
        background: var(--bg);
        color: var(--text);
        display: flex;
        min-height: 100vh;
    }

    /* ---- Sidebar ---- */
    .sidebar {
        width: var(--sidebar-w);
        background: linear-gradient(180deg, #1e1b4b 0%, #312e81 100%);
        color: #fff;
        display: flex;
        flex-direction: column;
        position: fixed;
        top: 0; left: 0; bottom: 0;
        z-index: 100;
        overflow-y: auto;
    }
    .sidebar-brand {
        padding: 24px 20px;
        font-size: 18px;
        font-weight: 700;
        letter-spacing: 1px;
        border-bottom: 1px solid rgba(255,255,255,.1);
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .sidebar-brand .icon { font-size: 22px; }
    .sidebar-nav { flex: 1; padding: 12px 0; }
    .sidebar-nav a {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 11px 20px;
        color: rgba(255,255,255,.7);
        text-decoration: none;
        font-size: 14px;
        transition: all .15s;
        border-left: 3px solid transparent;
    }
    .sidebar-nav a:hover { color: #fff; background: rgba(255,255,255,.08); }
    .sidebar-nav a.active {
        color: #fff;
        background: rgba(255,255,255,.12);
        border-left-color: #818cf8;
    }
    .sidebar-nav a .s-icon { font-size: 16px; width: 22px; text-align: center; }
    .sidebar-footer {
        padding: 14px 20px;
        font-size: 11px;
        color: rgba(255,255,255,.35);
        border-top: 1px solid rgba(255,255,255,.1);
    }

    /* ---- Main content ---- */
    .main {
        margin-left: var(--sidebar-w);
        flex: 1;
        padding: 28px 32px;
        min-width: 0;
    }
    .page-header {
        margin-bottom: 24px;
    }
    .page-header h1 {
        font-size: 22px;
        font-weight: 700;
        color: var(--text);
    }
    .page-header .breadcrumb {
        font-size: 13px;
        color: var(--text-secondary);
        margin-top: 4px;
    }
    .breadcrumb a { color: var(--primary); text-decoration: none; }
    .breadcrumb a:hover { text-decoration: underline; }

    /* ---- Cards ---- */
    .card {
        background: var(--surface);
        border-radius: var(--radius);
        box-shadow: 0 1px 3px rgba(0,0,0,.06);
        padding: 20px;
        margin-bottom: 20px;
    }
    .card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 16px;
    }
    .card-title {
        font-size: 15px;
        font-weight: 600;
        color: var(--text);
    }

    /* ---- Stats grid ---- */
    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
        gap: 16px;
        margin-bottom: 24px;
    }
    .stat-card {
        background: var(--surface);
        border-radius: var(--radius);
        padding: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,.06);
        display: flex;
        align-items: center;
        gap: 14px;
    }
    .stat-icon {
        width: 44px; height: 44px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
        flex-shrink: 0;
    }
    .stat-icon.users { background: #eef0ff; color: #4f6ef7; }
    .stat-icon.teams { background: #e0f2fe; color: #0ea5e9; }
    .stat-icon.txs   { background: #ecfdf5; color: #10b981; }
    .stat-icon.chats { background: #fef3c7; color: #f59e0b; }
    .stat-icon.files { background: #fce7f3; color: #ec4899; }
    .stat-info .stat-value {
        font-size: 26px;
        font-weight: 700;
        color: var(--text);
        line-height: 1.2;
    }
    .stat-info .stat-label {
        font-size: 13px;
        color: var(--text-secondary);
    }

    /* ---- Tables ---- */
    .table-wrap {
        border-radius: var(--radius);
        overflow: hidden;
        box-shadow: 0 1px 3px rgba(0,0,0,.06);
        background: var(--surface);
    }
    .table-wrap.scrollable {
        max-height: 520px;
        overflow-y: auto;
        overflow-x: auto;
    }
    .table-wrap.scrollable thead th {
        position: sticky;
        top: 0;
        z-index: 2;
    }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th {
        background: #f8fafc;
        color: var(--text-secondary);
        font-weight: 600;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: .5px;
        padding: 12px 14px;
        text-align: left;
        border-bottom: 2px solid var(--border);
        white-space: nowrap;
    }
    td {
        padding: 12px 14px;
        border-bottom: 1px solid var(--border);
        vertical-align: middle;
    }
    tr:last-child td { border-bottom: none; }
    tbody tr:hover { background: #f8fafc; }

    /* ---- Labels ---- */
    .label {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 100px;
        font-size: 12px;
        font-weight: 500;
    }
    .label.income  { background: #ecfdf5; color: #059669; }
    .label.expense { background: #fef2f2; color: #dc2626; }
    .label.user    { background: #eef0ff; color: #4f6ef7; }
    .label.assistant { background: #fdf2f8; color: #db2777; }
    .label.admin   { background: #fffbeb; color: #d97706; }
    .label.member  { background: #f3f4f6; color: #6b7280; }

    /* ---- Buttons ---- */
    .btn {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 8px 16px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        border: none;
        text-decoration: none;
        transition: all .15s;
        white-space: nowrap;
    }
    .btn:hover { opacity: .85; transform: translateY(-1px); }
    .btn-primary { background: var(--primary); color: #fff; }
    .btn-danger  { background: var(--danger); color: #fff; }
    .btn-success { background: var(--success); color: #fff; }
    .btn-outline { background: #fff; color: var(--primary); border: 1px solid var(--primary); }
    .btn-outline:hover { background: var(--primary-light); }
    .btn-sm { padding: 5px 12px; font-size: 12px; }
    .btn-xs { padding: 3px 8px; font-size: 11px; border-radius: 4px; }

    /* ---- Forms ---- */
    .form-row {
        display: flex;
        gap: 12px;
        align-items: flex-end;
        flex-wrap: wrap;
    }
    .form-group { display: flex; flex-direction: column; gap: 5px; }
    .form-group label {
        font-size: 12px;
        font-weight: 600;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: .3px;
    }
    .form-group input,
    .form-group select {
        padding: 9px 12px;
        border: 1px solid var(--border);
        border-radius: 6px;
        font-size: 14px;
        background: #fff;
        min-width: 160px;
        transition: border-color .15s;
    }
    .form-group input:focus,
    .form-group select:focus {
        outline: none;
        border-color: var(--primary);
        box-shadow: 0 0 0 3px rgba(79,110,247,.1);
    }

    .inline-edit {
        display: flex;
        gap: 6px;
        align-items: center;
    }
    .inline-edit input {
        padding: 6px 10px;
        border: 1px solid var(--border);
        border-radius: 4px;
        font-size: 13px;
        width: 90px;
    }
    .inline-edit select {
        padding: 6px 8px;
        border: 1px solid var(--border);
        border-radius: 4px;
        font-size: 12px;
    }

    .actions { display: flex; gap: 6px; flex-wrap: wrap; }
    .actions form { display: inline; }

    /* ---- Alerts ---- */
    .alert {
        padding: 12px 16px;
        border-radius: 8px;
        margin-bottom: 20px;
        font-size: 14px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .alert-success { background: var(--success-bg); color: #065f46; border: 1px solid #a7f3d0; }
    .alert-error   { background: var(--danger-bg); color: #991b1b; border: 1px solid #fecaca; }

    /* ---- Empty state ---- */
    .empty-state {
        text-align: center;
        padding: 40px 20px;
        color: var(--text-secondary);
    }
    .empty-state .empty-icon { font-size: 40px; margin-bottom: 10px; }
    .empty-state p { font-size: 14px; }

    /* ---- Meta ---- */
    .text-muted { color: var(--text-secondary); font-size: 12px; }
    .text-sm { font-size: 13px; }
    .mt-2 { margin-top: 8px; }
    code {
        background: #f1f5f9;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 13px;
        font-family: "SF Mono", monospace;
    }
"""

NAV_ITEMS = [
    ("dashboard",    "📊", "概览",       "/admin"),
    ("teams",        "👥", "团队管理",   "/admin/teams"),
    ("users",        "👤", "用户列表",   "/admin/users"),
    ("transactions", "💰", "交易记录",   "/admin/transactions"),
    ("chats",        "💬", "聊天记录",   "/admin/chats"),
    ("files",        "📁", "文件列表",   "/admin/files"),
]


def _scroll_table_class(row_count: int) -> str:
    return "table-wrap scrollable" if row_count > SCROLL_TABLE_THRESHOLD else "table-wrap"


def _generate_invite_code(length: int = 6) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


def _page_wrap(title: str, active: str, breadcrumb: str = "", extra_nav: str = "") -> str:
    sidebar = ""
    for key, icon, label, url in NAV_ITEMS:
        cls = "active" if key == active else ""
        sidebar += f'<a href="{url}" class="{cls}"><span class="s-icon">{icon}</span>{label}</a>'

    bc = ""
    if breadcrumb:
        bc = f'<div class="breadcrumb"><a href="/admin">首页</a> / {breadcrumb}</div>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - 内账管理后台</title>
<style>{ADMIN_STYLES}</style>
</head>
<body>
<aside class="sidebar">
    <div class="sidebar-brand"><span class="icon">📒</span> 内账后台</div>
    <nav class="sidebar-nav">{sidebar}</nav>
    <div class="sidebar-footer">v1.0 · 管理控制台</div>
</aside>
<main class="main">
<div class="page-header"><h1>{title}</h1>{bc}</div>
{extra_nav}
"""


_PAGE_TAIL = "\n</main>\n</body>\n</html>"


def _alert(msg: str, msg_type: str = "success") -> str:
    if not msg:
        return ""
    icon = "✓" if msg_type == "success" else "✗"
    return f'<div class="alert alert-{msg_type}"><strong>{icon}</strong> {msg}</div>'


# ==================== JSON API endpoints (unchanged) ====================


@router.get("/api/v1/admin/stats")
async def admin_stats(db: AsyncSession = Depends(get_db)):
    user_count = await db.scalar(select(sa_func.count(User.id)))
    team_count = await db.scalar(select(sa_func.count(Team.id)))
    tx_count = await db.scalar(select(sa_func.count(Transaction.id)))
    chat_count = await db.scalar(select(sa_func.count(ChatMessage.id)))
    file_count = await db.scalar(select(sa_func.count(FileRecord.id)))
    return {
        "user_count": user_count or 0,
        "team_count": team_count or 0,
        "transaction_count": tx_count or 0,
        "chat_message_count": chat_count or 0,
        "file_count": file_count or 0,
    }


@router.get("/api/v1/admin/teams")
async def admin_teams(db: AsyncSession = Depends(get_db)):
    teams_result = await db.execute(select(Team).order_by(Team.created_at.desc()))
    teams = teams_result.scalars().all()
    member_rows = await db.execute(
        select(User.team_id, sa_func.count(User.id))
        .where(User.team_id.isnot(None))
        .group_by(User.team_id)
    )
    member_counts = {row[0]: row[1] for row in member_rows.all()}
    tx_rows = await db.execute(
        select(Transaction.team_id, sa_func.count(Transaction.id)).group_by(Transaction.team_id)
    )
    tx_counts = {row[0]: row[1] for row in tx_rows.all()}
    return {
        "teams": [
            {
                "id": t.id,
                "name": t.name,
                "invite_code": t.invite_code,
                "member_count": member_counts.get(t.id, 0),
                "transaction_count": tx_counts.get(t.id, 0),
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in teams
        ]
    }


@router.get("/api/v1/admin/users")
async def admin_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User, Team)
        .outerjoin(Team, User.team_id == Team.id)
        .order_by(User.created_at.desc())
    )
    rows = result.all()
    return {
        "users": [
            {
                "id": user.id,
                "name": user.name,
                "phone": user.phone,
                "open_id": user.open_id,
                "role": user.role,
                "team_id": user.team_id,
                "team_name": team.name if team else None,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }
            for user, team in rows
        ]
    }


@router.get("/api/v1/admin/transactions")
async def admin_transactions(db: AsyncSession = Depends(get_db), limit: int = 100):
    result = await db.execute(
        select(Transaction).order_by(Transaction.created_at.desc()).limit(limit)
    )
    transactions = result.scalars().all()
    return {
        "transactions": [
            {
                "id": t.id,
                "team_id": t.team_id,
                "user_id": t.user_id,
                "type": t.type,
                "category": t.category,
                "amount": t.amount,
                "description": t.description,
                "product": t.product,
                "transaction_date": t.transaction_date.isoformat() if t.transaction_date else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in transactions
        ],
        "total_returned": len(transactions),
    }


@router.get("/api/v1/admin/chat-messages")
async def admin_chat_messages(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(50)
    )
    messages = result.scalars().all()
    return {
        "messages": [
            {
                "id": m.id,
                "team_id": m.team_id,
                "user_id": m.user_id,
                "role": m.role,
                "content_preview": m.content[:200] + ("..." if len(m.content) > 200 else ""),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]
    }


@router.get("/api/v1/admin/files")
async def admin_files(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FileRecord).order_by(FileRecord.created_at.desc()).limit(50)
    )
    files = result.scalars().all()
    return {
        "files": [
            {
                "id": f.id,
                "team_id": f.team_id,
                "user_id": f.user_id,
                "filename": f.filename,
                "url": f.url,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in files
        ]
    }


# ==================== Team CRUD (POST mutations) ====================


@router.post("/teams/create")
async def admin_create_team(
    name: str = Form(..., min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    invite_code = _generate_invite_code()
    team = Team(name=name, invite_code=invite_code)
    db.add(team)
    await db.flush()
    return RedirectResponse(url=f"/admin/teams?msg=团队「{name}」创建成功&msg_type=success", status_code=303)


@router.post("/teams/{team_id}/update")
async def admin_update_team(
    team_id: int,
    name: str = Form(..., min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        return RedirectResponse(url=f"/admin/teams?msg=团队不存在&msg_type=error", status_code=303)
    team.name = name
    await db.flush()
    return RedirectResponse(url=f"/admin/teams?msg=团队名称已更新&msg_type=success", status_code=303)


@router.post("/teams/{team_id}/delete")
async def admin_delete_team(team_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        return RedirectResponse(url=f"/admin/teams?msg=团队不存在&msg_type=error", status_code=303)
    await db.execute(delete(Transaction).where(Transaction.team_id == team_id))
    await db.execute(delete(ChatMessage).where(ChatMessage.team_id == team_id))
    await db.execute(delete(FileRecord).where(FileRecord.team_id == team_id))
    await db.execute(delete(TransactionProposal).where(TransactionProposal.team_id == team_id))
    await db.execute(
        User.__table__.update().where(User.team_id == team_id).values(team_id=None, role="member")
    )
    await db.delete(team)
    await db.flush()
    return RedirectResponse(url=f"/admin/teams?msg=团队已删除&msg_type=success", status_code=303)


@router.post("/teams/{team_id}/regenerate-code")
async def admin_regenerate_code(team_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        return RedirectResponse(url=f"/admin/teams?msg=团队不存在&msg_type=error", status_code=303)
    team.invite_code = _generate_invite_code()
    await db.flush()
    return RedirectResponse(url=f"/admin/teams?msg=邀请码已重新生成&msg_type=success", status_code=303)


# ==================== Member mutations ====================


@router.post("/teams/{team_id}/members/add")
async def admin_add_member(
    team_id: int,
    phone: str = Form(..., min_length=1, max_length=20),
    name: str = Form(default="", max_length=50),
    role: str = Form(default="member"),
    db: AsyncSession = Depends(get_db),
):
    if role not in ("admin", "member"):
        role = "member"

    team_result = await db.execute(select(Team).where(Team.id == team_id))
    if team_result.scalar_one_or_none() is None:
        return RedirectResponse(url=f"/admin/teams?msg=团队不存在&msg_type=error", status_code=303)

    # Find user by phone or create a new one
    user_result = await db.execute(select(User).where(User.phone == phone))
    user = user_result.scalar_one_or_none()

    if user is None:
        user = User(phone=phone, name=name, role=role, team_id=team_id)
        db.add(user)
        await db.flush()
        display = f"「{name or phone}」（新用户）"
    else:
        if name:
            user.name = name
        user.team_id = team_id
        user.role = role
        await db.flush()
        display = f"「{user.name or phone}」"

    return RedirectResponse(
        url=f"/admin/teams/{team_id}?msg=成员{display}已添加&msg_type=success", status_code=303
    )


@router.post("/teams/{team_id}/members/{user_id}/update")
async def admin_update_member(
    team_id: int, user_id: int,
    name: str = Form(default="", max_length=50),
    role: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.id == user_id, User.team_id == team_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        return RedirectResponse(url=f"/admin/teams/{team_id}?msg=成员不存在&msg_type=error", status_code=303)
    if role == "member" and user.role == "admin":
        admin_count = await db.scalar(
            select(sa_func.count(User.id)).where(User.team_id == team_id, User.role == "admin")
        )
        if (admin_count or 0) <= 1:
            return RedirectResponse(url=f"/admin/teams/{team_id}?msg=不能降级团队的最后一位管理员&msg_type=error", status_code=303)
    if name:
        user.name = name
    if role:
        user.role = role
    await db.flush()
    return RedirectResponse(url=f"/admin/teams/{team_id}?msg=成员信息已更新&msg_type=success", status_code=303)


@router.post("/teams/{team_id}/members/{user_id}/remove")
async def admin_remove_member(team_id: int, user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.id == user_id, User.team_id == team_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        return RedirectResponse(url=f"/admin/teams/{team_id}?msg=成员不存在&msg_type=error", status_code=303)
    if user.role == "admin":
        admin_count = await db.scalar(
            select(sa_func.count(User.id)).where(User.team_id == team_id, User.role == "admin")
        )
        if (admin_count or 0) <= 1:
            return RedirectResponse(url=f"/admin/teams/{team_id}?msg=不能移除团队的最后一位管理员&msg_type=error", status_code=303)
    user.team_id = None
    user.role = "member"
    await db.flush()
    return RedirectResponse(url=f"/admin/teams/{team_id}?msg=成员已移除&msg_type=success", status_code=303)


# ==================== Page: Dashboard ====================


@router.get("", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    msg: str = Query(default=""),
    msg_type: str = Query(default="success"),
    db: AsyncSession = Depends(get_db),
):
    stats = await admin_stats(db)

    html = _page_wrap("系统概览", "dashboard")
    html += _alert(msg, msg_type)

    # Stat cards
    html += f"""
    <section class="stats-grid">
        <div class="stat-card">
            <div class="stat-icon users">👤</div>
            <div class="stat-info">
                <div class="stat-value">{stats['user_count']}</div>
                <div class="stat-label">用户总数</div>
            </div>
        </div>
        <div class="stat-card">
            <div class="stat-icon teams">👥</div>
            <div class="stat-info">
                <div class="stat-value">{stats['team_count']}</div>
                <div class="stat-label">团队总数</div>
            </div>
        </div>
        <div class="stat-card">
            <div class="stat-icon txs">💰</div>
            <div class="stat-info">
                <div class="stat-value">{stats['transaction_count']}</div>
                <div class="stat-label">交易记录</div>
            </div>
        </div>
        <div class="stat-card">
            <div class="stat-icon chats">💬</div>
            <div class="stat-info">
                <div class="stat-value">{stats['chat_message_count']}</div>
                <div class="stat-label">聊天消息</div>
            </div>
        </div>
        <div class="stat-card">
            <div class="stat-icon files">📁</div>
            <div class="stat-info">
                <div class="stat-value">{stats['file_count']}</div>
                <div class="stat-label">文件数量</div>
            </div>
        </div>
    </section>
    """

    # Quick links
    html += """
    <div class="card">
        <div class="card-header"><span class="card-title">快捷入口</span></div>
        <div style="display:flex;gap:12px;flex-wrap:wrap;">
            <a href="/admin/teams" class="btn btn-primary">👥 管理团队</a>
            <a href="/admin/users" class="btn btn-outline">👤 查看用户</a>
            <a href="/admin/transactions" class="btn btn-outline">💰 查看交易</a>
            <a href="/admin/chats" class="btn btn-outline">💬 聊天记录</a>
            <a href="/admin/files" class="btn btn-outline">📁 文件列表</a>
        </div>
    </div>
    """

    html += _PAGE_TAIL
    return HTMLResponse(content=html)


# ==================== Page: Teams list ====================


@router.get("/teams", response_class=HTMLResponse)
async def admin_teams_page(
    request: Request,
    msg: str = Query(default=""),
    msg_type: str = Query(default="success"),
    db: AsyncSession = Depends(get_db),
):
    teams_resp = await admin_teams(db)
    teams = teams_resp["teams"]

    html = _page_wrap("团队管理", "teams", "团队管理")
    html += _alert(msg, msg_type)

    # Create form
    html += """
    <div class="card">
        <div class="card-header"><span class="card-title">创建新团队</span></div>
        <form action="/admin/teams/create" method="post">
            <div class="form-row">
                <div class="form-group">
                    <label>团队名称</label>
                    <input type="text" name="name" placeholder="输入团队名称" maxlength="100" required />
                </div>
                <div class="form-group">
                    <label>&nbsp;</label>
                    <button type="submit" class="btn btn-primary">创建团队</button>
                </div>
            </div>
        </form>
    </div>
    """

    # Team table
    html += '<div class="card"><div class="card-header">'
    html += f'<span class="card-title">团队列表</span>'
    html += f'<span class="text-muted text-sm">共 {len(teams)} 个团队</span>'
    html += '</div>'

    if teams:
        html += f'<div class="{_scroll_table_class(len(teams))}"><table>'
        html += "<thead><tr><th>ID</th><th>名称</th><th>邀请码</th><th>成员</th><th>交易</th><th>创建时间</th><th>操作</th></tr></thead><tbody>"
        for t in teams:
            html += (
                f"<tr>"
                f"<td>{t['id']}</td>"
                f"<td><strong>{t['name']}</strong></td>"
                f"<td><code>{t['invite_code']}</code></td>"
                f"<td>{t['member_count']}</td>"
                f"<td>{t['transaction_count']}</td>"
                f"<td class='text-muted'>{t['created_at']}</td>"
                f"<td><div class='actions'>"
                f"<a href='/admin/teams/{t['id']}' class='btn btn-primary btn-xs'>管理成员</a>"
                f"<form action='/admin/teams/{t['id']}/regenerate-code' method='post'>"
                f"<button class='btn btn-outline btn-xs'>新邀请码</button>"
                f"</form>"
                f"<form action='/admin/teams/{t['id']}/delete' method='post' "
                f"onsubmit=\"return confirm('确定要删除团队「{t['name']}」吗？')\">"
                f"<button class='btn btn-danger btn-xs'>删除</button>"
                f"</form>"
                f"</div></td></tr>"
            )
        html += "</tbody></table></div>"
    else:
        html += '<div class="empty-state"><div class="empty-icon">👥</div><p>暂无团队</p></div>'

    html += "</div>"
    html += _PAGE_TAIL
    return HTMLResponse(content=html)


# ==================== Page: Team detail / members ====================


@router.get("/teams/{team_id}", response_class=HTMLResponse)
async def admin_team_detail(
    team_id: int,
    request: Request,
    msg: str = Query(default=""),
    msg_type: str = Query(default="success"),
    db: AsyncSession = Depends(get_db),
):
    team_result = await db.execute(select(Team).where(Team.id == team_id))
    team = team_result.scalar_one_or_none()
    if team is None:
        html = _page_wrap("团队不存在", "teams") + _alert("团队不存在", "error") + _PAGE_TAIL
        return HTMLResponse(content=html, status_code=404)

    members_result = await db.execute(
        select(User).where(User.team_id == team_id).order_by(User.role.desc(), User.id)
    )
    members = members_result.scalars().all()

    available_result = await db.execute(
        select(User)
        .where((User.team_id != team_id) | (User.team_id.is_(None)))
        .order_by(User.id).limit(100)
    )
    available_users = available_result.scalars().all()

    html = _page_wrap(f"团队: {team.name}", "teams", f'<a href="/admin/teams">团队管理</a> / {team.name}')
    html += _alert(msg, msg_type)

    # Team info card
    html += f"""
    <div class="card">
        <div class="card-header"><span class="card-title">团队信息</span></div>
        <div class="form-row">
            <div class="form-group">
                <label>ID</label>
                <span style="padding:9px 0;font-size:14px;">{team.id}</span>
            </div>
            <form action="/admin/teams/{team.id}/update" method="post">
                <div class="form-group">
                    <label>名称</label>
                    <div class="inline-edit">
                        <input type="text" name="name" value="{team.name}" maxlength="100" required style="width:150px;"/>
                        <button type="submit" class="btn btn-primary btn-sm">保存</button>
                    </div>
                </div>
            </form>
            <div class="form-group">
                <label>邀请码</label>
                <span style="padding:9px 0;font-size:14px;"><code>{team.invite_code}</code></span>
            </div>
            <form action="/admin/teams/{team.id}/regenerate-code" method="post">
                <div class="form-group"><label>&nbsp;</label>
                    <button type="submit" class="btn btn-outline btn-sm">重新生成</button>
                </div>
            </form>
            <form action="/admin/teams/{team.id}/delete" method="post"
                  onsubmit="return confirm('确定要删除团队「{team.name}」吗？')">
                <div class="form-group"><label>&nbsp;</label>
                    <button type="submit" class="btn btn-danger btn-sm">删除团队</button>
                </div>
            </form>
        </div>
    </div>
    """

    # Members card
    member_count = len(members)
    html += f"""
    <div class="card">
        <div class="card-header">
            <span class="card-title">团队成员</span>
            <span class="text-muted text-sm">{member_count} 人</span>
        </div>
    """

    if member_count > 0:
        html += f'<div class="{_scroll_table_class(member_count)}"><table>'
        html += "<thead><tr><th>ID</th><th>名称</th><th>手机</th><th>角色</th><th>修改名称</th><th>修改角色</th><th>操作</th></tr></thead><tbody>"
        for m in members:
            html += f"""
            <tr>
                <td>{m.id}</td>
                <td><strong>{m.name or '-'}</strong></td>
                <td class="text-muted">{m.phone or '-'}</td>
                <td><span class="label {m.role}">{'管理员' if m.role == 'admin' else '成员'}</span></td>
                <td>
                    <form action="/admin/teams/{team.id}/members/{m.id}/update" method="post">
                        <div class="inline-edit">
                            <input type="text" name="name" value="{m.name or ''}" placeholder="名称" maxlength="50"/>
                            <input type="hidden" name="role" value="{m.role}"/>
                            <button class="btn btn-primary btn-xs">改</button>
                        </div>
                    </form>
                </td>
                <td>
                    <form action="/admin/teams/{team.id}/members/{m.id}/update" method="post">
                        <div class="inline-edit">
                            <select name="role">
                                <option value="admin" {'selected' if m.role == 'admin' else ''}>管理员</option>
                                <option value="member" {'selected' if m.role == 'member' else ''}>成员</option>
                            </select>
                            <input type="hidden" name="name" value="{m.name or ''}"/>
                            <button class="btn btn-primary btn-xs">改</button>
                        </div>
                    </form>
                </td>
                <td>
                    <form action="/admin/teams/{team.id}/members/{m.id}/remove" method="post"
                          onsubmit="return confirm('确定要移除该成员吗？')">
                        <button class="btn btn-danger btn-xs">移除</button>
                    </form>
                </td>
            </tr>
            """
        html += "</tbody></table></div>"
    else:
        html += '<div class="empty-state"><p>暂无成员</p></div>'

    html += "</div>"

    # Add member card
    html += f"""
    <div class="card">
        <div class="card-header"><span class="card-title">添加成员</span></div>
        <form action="/admin/teams/{team.id}/members/add" method="post">
            <div class="form-row">
                <div class="form-group">
                    <label>手机号 *</label>
                    <input type="text" name="phone" placeholder="输入手机号" maxlength="20" required style="min-width:140px;" />
                </div>
                <div class="form-group">
                    <label>姓名</label>
                    <input type="text" name="name" placeholder="输入姓名" maxlength="50" style="min-width:120px;" />
                </div>
                <div class="form-group">
                    <label>角色</label>
                    <select name="role">
                        <option value="member">成员</option>
                        <option value="admin">管理员</option>
                    </select>
                </div>
    """
    if available_users:
        html += """
                <div class="form-group">
                    <label>或快速选择已有用户</label>
                    <select onchange="var p=this.selectedOptions[0].dataset; if(this.value){this.form.phone.value=p.phone; this.form.name.value=p.name;}">
                        <option value="">-- 请选择 --</option>
        """
        for u in available_users:
            label = f"#{u.id} {u.name or '(无名)'}"
            phone = u.phone or ''
            name = u.name or ''
            html += f'<option value="{u.id}" data-phone="{phone}" data-name="{name}">{label}</option>\n'
        html += """
                    </select>
                </div>
        """
    html += """
                <div class="form-group">
                    <label>&nbsp;</label>
                    <button type="submit" class="btn btn-primary">添加到团队</button>
                </div>
            </div>
        </form>
    </div>
    """

    html += _PAGE_TAIL
    return HTMLResponse(content=html)


# ==================== Page: Users ====================


@router.get("/users", response_class=HTMLResponse)
async def admin_users_page(
    request: Request,
    msg: str = Query(default=""),
    msg_type: str = Query(default="success"),
    db: AsyncSession = Depends(get_db),
):
    users_resp = await admin_users(db)
    users = users_resp["users"]

    html = _page_wrap("用户列表", "users", "用户列表")
    html += _alert(msg, msg_type)

    html += f"""
    <div class="card">
        <div class="card-header">
            <span class="card-title">所有用户</span>
            <span class="text-muted text-sm">共 {len(users)} 人</span>
        </div>
    """

    if users:
        html += f'<div class="{_scroll_table_class(len(users))}"><table>'
        html += "<thead><tr><th>ID</th><th>名称</th><th>手机</th><th>OpenID</th><th>角色</th><th>所属团队</th><th>创建时间</th></tr></thead><tbody>"
        for u in users:
            role = u["role"] or "member"
            role_label = "管理员" if role == "admin" else "成员"
            html += (
                f"<tr>"
                f"<td>{u['id']}</td>"
                f"<td><strong>{u['name']}</strong></td>"
                f"<td class='text-muted'>{u['phone'] or '-'}</td>"
                f"<td class='text-muted text-sm'>{u['open_id'] or '-'}</td>"
                f"<td><span class='label {role}'>{role_label}</span></td>"
                f"<td>{u['team_name'] or '<span class=text-muted>-</span>'}</td>"
                f"<td class='text-muted'>{u['created_at']}</td>"
                f"</tr>"
            )
        html += "</tbody></table></div>"
    else:
        html += '<div class="empty-state"><div class="empty-icon">👤</div><p>暂无用户</p></div>'

    html += "</div>" + _PAGE_TAIL
    return HTMLResponse(content=html)


# ==================== Page: Transactions ====================


@router.get("/transactions", response_class=HTMLResponse)
async def admin_transactions_page(
    request: Request,
    msg: str = Query(default=""),
    msg_type: str = Query(default="success"),
    db: AsyncSession = Depends(get_db),
):
    txs_resp = await admin_transactions(db, limit=200)
    transactions = txs_resp["transactions"]

    html = _page_wrap("交易记录", "transactions", "交易记录")
    html += _alert(msg, msg_type)

    income_total = sum(t["amount"] for t in transactions if t["type"] == "income")
    expense_total = sum(t["amount"] for t in transactions if t["type"] == "expense")

    html += f"""
    <div class="card">
        <div class="card-header">
            <span class="card-title">最近交易</span>
            <span class="text-muted text-sm">共 {len(transactions)} 条</span>
        </div>
        <div style="display:flex;gap:24px;margin-bottom:16px;">
            <div><span class="text-muted text-sm">收入合计:</span> <strong style="color:#059669;">¥{income_total:.2f}</strong></div>
            <div><span class="text-muted text-sm">支出合计:</span> <strong style="color:#dc2626;">¥{expense_total:.2f}</strong></div>
            <div><span class="text-muted text-sm">结余:</span> <strong style="color:{'#059669' if income_total >= expense_total else '#dc2626'};">¥{income_total - expense_total:.2f}</strong></div>
        </div>
    """

    if transactions:
        html += f'<div class="{_scroll_table_class(len(transactions))}"><table>'
        html += "<thead><tr><th>ID</th><th>团队</th><th>用户</th><th>类型</th><th>金额</th><th>类别</th><th>描述</th><th>产品</th><th>交易日期</th></tr></thead><tbody>"
        for t in transactions:
            label_class = t["type"]
            type_label = "收入" if t["type"] == "income" else "支出"
            html += (
                f"<tr>"
                f"<td>{t['id']}</td>"
                f"<td>{t['team_id']}</td>"
                f"<td>{t['user_id']}</td>"
                f"<td><span class='label {label_class}'>{type_label}</span></td>"
                f"<td><strong>¥{t['amount']:.2f}</strong></td>"
                f"<td>{t['category']}</td>"
                f"<td class='text-muted'>{t['description'] or '-'}</td>"
                f"<td>{t['product'] or '-'}</td>"
                f"<td class='text-muted'>{t['transaction_date']}</td>"
                f"</tr>"
            )
        html += "</tbody></table></div>"
    else:
        html += '<div class="empty-state"><div class="empty-icon">💰</div><p>暂无交易记录</p></div>'

    html += "</div>" + _PAGE_TAIL
    return HTMLResponse(content=html)


# ==================== Page: Chats ====================


@router.get("/chats", response_class=HTMLResponse)
async def admin_chats_page(
    request: Request,
    msg: str = Query(default=""),
    msg_type: str = Query(default="success"),
    db: AsyncSession = Depends(get_db),
):
    chats_resp = await admin_chat_messages(db)
    messages = chats_resp["messages"]

    html = _page_wrap("聊天记录", "chats", "聊天记录")
    html += _alert(msg, msg_type)

    html += f"""
    <div class="card">
        <div class="card-header">
            <span class="card-title">最近消息</span>
            <span class="text-muted text-sm">共 {len(messages)} 条</span>
        </div>
    """

    if messages:
        html += '<div class="table-wrap"><table>'
        html += "<thead><tr><th>ID</th><th>团队</th><th>用户</th><th>角色</th><th>内容预览</th><th>时间</th></tr></thead><tbody>"
        for m in messages:
            role_label = {"user": "用户", "assistant": "助手", "tool": "工具"}.get(m["role"], m["role"])
            html += (
                f"<tr>"
                f"<td>{m['id']}</td>"
                f"<td>{m['team_id']}</td>"
                f"<td>{m['user_id']}</td>"
                f"<td><span class='label {m['role']}'>{role_label}</span></td>"
                f"<td class='text-muted text-sm'>{m['content_preview']}</td>"
                f"<td class='text-muted'>{m['created_at']}</td>"
                f"</tr>"
            )
        html += "</tbody></table></div>"
    else:
        html += '<div class="empty-state"><div class="empty-icon">💬</div><p>暂无聊天记录</p></div>'

    html += "</div>" + _PAGE_TAIL
    return HTMLResponse(content=html)


# ==================== Page: Files ====================


@router.get("/files", response_class=HTMLResponse)
async def admin_files_page(
    request: Request,
    msg: str = Query(default=""),
    msg_type: str = Query(default="success"),
    db: AsyncSession = Depends(get_db),
):
    files_resp = await admin_files(db)
    files = files_resp["files"]

    html = _page_wrap("文件列表", "files", "文件列表")
    html += _alert(msg, msg_type)

    html += f"""
    <div class="card">
        <div class="card-header">
            <span class="card-title">最近上传</span>
            <span class="text-muted text-sm">共 {len(files)} 个</span>
        </div>
    """

    if files:
        html += '<div class="table-wrap"><table>'
        html += "<thead><tr><th>ID</th><th>团队</th><th>用户</th><th>文件名</th><th>URL</th><th>上传时间</th></tr></thead><tbody>"
        for f in files:
            html += (
                f"<tr>"
                f"<td>{f['id']}</td>"
                f"<td>{f['team_id']}</td>"
                f"<td>{f['user_id']}</td>"
                f"<td><strong>{f['filename']}</strong></td>"
                f"<td class='text-muted text-sm' style='max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>{f['url']}</td>"
                f"<td class='text-muted'>{f['created_at']}</td>"
                f"</tr>"
            )
        html += "</tbody></table></div>"
    else:
        html += '<div class="empty-state"><div class="empty-icon">📁</div><p>暂无文件</p></div>'

    html += "</div>" + _PAGE_TAIL
    return HTMLResponse(content=html)
