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

ADMIN_STYLES = """
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; background: #f5f5f5; color: #333; }
    h1, h2 { color: #1a1a2e; }
    .stats { display: flex; gap: 15px; margin: 20px 0; flex-wrap: wrap; }
    .stat-card { background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); flex: 1; min-width: 150px; text-align: center; }
    .stat-card h3 { margin: 0 0 10px 0; font-size: 14px; color: #666; }
    .stat-card .value { font-size: 28px; font-weight: bold; color: #1a1a2e; }
  .nav { margin: 12px 0 24px; display: flex; flex-wrap: wrap; gap: 10px; }
  .nav a { color: #1565c0; text-decoration: none; font-size: 14px; padding: 6px 12px; background: #fff; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  .nav a:hover { background: #e3f2fd; }
    table { width: 100%; border-collapse: collapse; background: white; font-size: 13px; }
    th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #eee; }
    th { background: #1a1a2e; color: white; font-weight: 600; }
    tr:hover { background: #f0f0ff; }
    .section { margin-bottom: 30px; }
  .section-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
  .section-meta { font-size: 13px; color: #666; }
    .label { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
    .label.income { background: #e8f5e9; color: #2e7d32; }
    .label.expense { background: #fbe9e7; color: #c62828; }
    .label.user { background: #e3f2fd; color: #1565c0; }
    .label.assistant { background: #f3e5f5; color: #7b1fa2; }
    .label.admin { background: #fff3e0; color: #e65100; }
    .label.member { background: #eceff1; color: #455a64; }
  .table-wrap { border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); background: white; }
  .table-wrap.scrollable { max-height: 520px; overflow-y: auto; overflow-x: auto; }
  .table-wrap.scrollable thead th { position: sticky; top: 0; z-index: 1; box-shadow: 0 1px 0 #333; }

  /* Forms */
  .form-card { background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }
  .form-card h3 { margin: 0 0 14px 0; font-size: 16px; color: #1a1a2e; }
  .form-row { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
  .form-group { display: flex; flex-direction: column; gap: 4px; }
  .form-group label { font-size: 12px; color: #666; font-weight: 600; }
  .form-group input, .form-group select { padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; min-width: 160px; }
  .form-group input:focus, .form-group select:focus { outline: none; border-color: #1989fa; }

  /* Buttons */
  .btn { display: inline-block; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; text-decoration: none; }
  .btn:hover { opacity: 0.85; }
  .btn-primary { background: #1989fa; color: #fff; }
  .btn-danger { background: #e53935; color: #fff; }
  .btn-sm { padding: 4px 10px; font-size: 12px; }
  .btn-outline { background: #fff; color: #1565c0; border: 1px solid #1565c0; }
  .btn-outline:hover { background: #e3f2fd; }

  /* Inline actions */
  .actions { display: flex; gap: 6px; flex-wrap: wrap; }
  .actions form { display: inline; }

  /* Alert messages */
  .alert { padding: 12px 16px; border-radius: 6px; margin-bottom: 16px; font-size: 14px; }
  .alert-success { background: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7; }
  .alert-error { background: #ffebee; color: #c62828; border: 1px solid #ef9a9a; }

  /* Inline edit */
  .inline-edit { display: flex; gap: 8px; align-items: center; }
  .inline-edit input { padding: 6px 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 13px; width: 120px; }
  .back-link { display: inline-block; margin-bottom: 16px; color: #1565c0; text-decoration: none; font-size: 14px; }
  .back-link:hover { text-decoration: underline; }
"""


def _scroll_table_class(row_count: int) -> str:
    if row_count > SCROLL_TABLE_THRESHOLD:
        return "table-wrap scrollable"
    return "table-wrap"


def _section_heading(title: str, row_count: int) -> str:
    scroll_hint = ""
    if row_count > SCROLL_TABLE_THRESHOLD:
        scroll_hint = f'<span class="section-meta">共 {row_count} 条，可滚动查看</span>'
    return f'<div class="section-head"><h2>{title}</h2>{scroll_hint}</div>'


def _generate_invite_code(length: int = 6) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


def _page_head(title: str, extra_nav: str = "") -> str:
    nav_items = [
        ('/admin', '首页'),
        ('/admin#teams', '团队管理'),
        ('/admin#users', '用户'),
        ('/admin#transactions', '交易'),
        ('/admin#chats', '聊天'),
        ('/admin#files', '文件'),
    ]
    nav_html = "".join(f'<a href="{url}">{label}</a>' for url, label in nav_items)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - 内账管理后台</title>
    <style>{ADMIN_STYLES}</style>
</head>
<body>
    <h1>内账管理后台</h1>
    <nav class="nav">{nav_html}</nav>
    {extra_nav}
"""


_PAGE_TAIL = """
</body>
</html>"""


def _alert(msg: str, msg_type: str = "success") -> str:
    if not msg:
        return ""
    return f'<div class="alert alert-{msg_type}">{msg}</div>'


# ---- Data endpoints (unchanged) ----


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


# ---- Team CRUD endpoints ----


@router.post("/teams/create")
async def admin_create_team(
    name: str = Form(..., min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    invite_code = _generate_invite_code()
    team = Team(name=name, invite_code=invite_code)
    db.add(team)
    await db.flush()
    return RedirectResponse(url=f"/admin?msg=团队「{name}」创建成功&msg_type=success#teams", status_code=303)


@router.post("/teams/{team_id}/update")
async def admin_update_team(
    team_id: int,
    name: str = Form(..., min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        return RedirectResponse(url=f"/admin?msg=团队不存在&msg_type=error", status_code=303)
    team.name = name
    await db.flush()
    return RedirectResponse(url=f"/admin?msg=团队名称已更新&msg_type=success#teams", status_code=303)


@router.post("/teams/{team_id}/delete")
async def admin_delete_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        return RedirectResponse(url=f"/admin?msg=团队不存在&msg_type=error", status_code=303)

    # Cascade clean associated data
    await db.execute(delete(Transaction).where(Transaction.team_id == team_id))
    await db.execute(delete(ChatMessage).where(ChatMessage.team_id == team_id))
    await db.execute(delete(FileRecord).where(FileRecord.team_id == team_id))
    await db.execute(delete(TransactionProposal).where(TransactionProposal.team_id == team_id))

    # Detach members
    await db.execute(
        User.__table__.update().where(User.team_id == team_id).values(team_id=None, role="member")
    )

    await db.delete(team)
    await db.flush()
    return RedirectResponse(url=f"/admin?msg=团队已删除&msg_type=success#teams", status_code=303)


@router.post("/teams/{team_id}/regenerate-code")
async def admin_regenerate_code(
    team_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        return RedirectResponse(url=f"/admin?msg=团队不存在&msg_type=error", status_code=303)
    team.invite_code = _generate_invite_code()
    await db.flush()
    return RedirectResponse(url=f"/admin?msg=邀请码已重新生成&msg_type=success#teams", status_code=303)


# ---- Member management endpoints ----


@router.post("/teams/{team_id}/members/add")
async def admin_add_member(
    team_id: int,
    user_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Verify team exists
    team_result = await db.execute(select(Team).where(Team.id == team_id))
    if team_result.scalar_one_or_none() is None:
        return RedirectResponse(url=f"/admin?msg=团队不存在&msg_type=error", status_code=303)

    # Verify user exists
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        url = f"/admin/teams/{team_id}?msg=用户不存在&msg_type=error"
        return RedirectResponse(url=url, status_code=303)

    user.team_id = team_id
    user.role = "member"
    await db.flush()
    url = f"/admin/teams/{team_id}?msg=成员「{user.name or user_id}」已添加&msg_type=success"
    return RedirectResponse(url=url, status_code=303)


@router.post("/teams/{team_id}/members/{user_id}/update")
async def admin_update_member(
    team_id: int,
    user_id: int,
    name: str = Form(default="", max_length=50),
    role: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.id == user_id, User.team_id == team_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        url = f"/admin/teams/{team_id}?msg=成员不存在&msg_type=error"
        return RedirectResponse(url=url, status_code=303)

    # Prevent demoting the last admin
    if role == "member" and user.role == "admin":
        admin_count = await db.scalar(
            select(sa_func.count(User.id)).where(
                User.team_id == team_id, User.role == "admin"
            )
        )
        if (admin_count or 0) <= 1:
            url = f"/admin/teams/{team_id}?msg=不能移除或降级团队的最后一位管理员&msg_type=error"
            return RedirectResponse(url=url, status_code=303)

    if name:
        user.name = name
    if role:
        user.role = role
    await db.flush()
    url = f"/admin/teams/{team_id}?msg=成员信息已更新&msg_type=success"
    return RedirectResponse(url=url, status_code=303)


@router.post("/teams/{team_id}/members/{user_id}/remove")
async def admin_remove_member(
    team_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.id == user_id, User.team_id == team_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        url = f"/admin/teams/{team_id}?msg=成员不存在&msg_type=error"
        return RedirectResponse(url=url, status_code=303)

    # Prevent removing the last admin
    if user.role == "admin":
        admin_count = await db.scalar(
            select(sa_func.count(User.id)).where(
                User.team_id == team_id, User.role == "admin"
            )
        )
        if (admin_count or 0) <= 1:
            url = f"/admin/teams/{team_id}?msg=不能移除团队的最后一位管理员&msg_type=error"
            return RedirectResponse(url=url, status_code=303)

    user.team_id = None
    user.role = "member"
    await db.flush()
    url = f"/admin/teams/{team_id}?msg=成员已移除&msg_type=success"
    return RedirectResponse(url=url, status_code=303)


# ---- Team detail page ----


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
        return HTMLResponse(
            content=_page_head("团队不存在") + _alert("团队不存在", "error") + _PAGE_TAIL,
            status_code=404,
        )

    # Team members
    members_result = await db.execute(
        select(User).where(User.team_id == team_id).order_by(User.role.desc(), User.id)
    )
    members = members_result.scalars().all()

    # Users not in this team (for the "add member" dropdown)
    available_result = await db.execute(
        select(User)
        .where((User.team_id != team_id) | (User.team_id.is_(None)))
        .order_by(User.id)
        .limit(100)
    )
    available_users = available_result.scalars().all()

    html = _page_head(f"团队: {team.name}",
        extra_nav=f'<a href="/admin#teams" class="back-link">← 返回团队列表</a>')
    html += _alert(msg, msg_type)

    # Team info card
    html += f"""
    <div class="form-card">
        <h3>团队信息</h3>
        <div class="form-row">
            <div class="form-group">
                <label>ID</label>
                <span style="padding:8px 0;font-size:14px;">{team.id}</span>
            </div>
            <form action="/admin/teams/{team.id}/update" method="post">
                <div class="form-group">
                    <label>名称</label>
                    <div class="inline-edit">
                        <input type="text" name="name" value="{team.name}" maxlength="100" required />
                        <button type="submit" class="btn btn-primary btn-sm">保存</button>
                    </div>
                </div>
            </form>
            <div class="form-group">
                <label>邀请码</label>
                <span style="padding:8px 0;font-size:14px;"><code>{team.invite_code}</code></span>
            </div>
            <form action="/admin/teams/{team.id}/regenerate-code" method="post">
                <div class="form-group">
                    <label>&nbsp;</label>
                    <button type="submit" class="btn btn-outline btn-sm">重新生成邀请码</button>
                </div>
            </form>
            <form action="/admin/teams/{team.id}/delete" method="post" onsubmit="return confirm('确定要删除团队「{team.name}」吗？这将清除所有关联数据。')">
                <div class="form-group">
                    <label>&nbsp;</label>
                    <button type="submit" class="btn btn-danger btn-sm">删除团队</button>
                </div>
            </form>
        </div>
    </div>
    """

    # Members section
    member_count = len(members)
    html += f"""
    <div class="section">
        {_section_heading(f"团队成员 ({member_count}人)", member_count)}
    """

    if member_count > 0:
        html += f"""
        <div class="{_scroll_table_class(member_count)}">
        <table>
            <thead><tr>
                <th>ID</th><th>名称</th><th>手机</th><th>角色</th>
                <th>名称修改</th><th>角色修改</th><th>操作</th>
            </tr></thead>
            <tbody>
        """
        for m in members:
            html += f"""
            <tr>
                <td>{m.id}</td>
                <td>{m.name or '-'}</td>
                <td>{m.phone or '-'}</td>
                <td><span class="label {m.role}">{m.role}</span></td>
                <td>
                    <form action="/admin/teams/{team.id}/members/{m.id}/update" method="post">
                        <div class="inline-edit">
                            <input type="text" name="name" value="{m.name or ''}" placeholder="输入名称" maxlength="50" style="width:80px;" />
                            <input type="hidden" name="role" value="{m.role}" />
                            <button type="submit" class="btn btn-primary btn-sm">改</button>
                        </div>
                    </form>
                </td>
                <td>
                    <form action="/admin/teams/{team.id}/members/{m.id}/update" method="post">
                        <div class="inline-edit">
                            <select name="role" style="padding:6px 8px;border:1px solid #ddd;border-radius:4px;font-size:12px;">
                                <option value="admin" {'selected' if m.role == 'admin' else ''}>管理员</option>
                                <option value="member" {'selected' if m.role == 'member' else ''}>成员</option>
                            </select>
                            <input type="hidden" name="name" value="{m.name or ''}" />
                            <button type="submit" class="btn btn-primary btn-sm">改</button>
                        </div>
                    </form>
                </td>
                <td>
                    <form action="/admin/teams/{team.id}/members/{m.id}/remove" method="post" onsubmit="return confirm('确定要移除该成员吗？')">
                        <button type="submit" class="btn btn-danger btn-sm">移除</button>
                    </form>
                </td>
            </tr>
            """
        html += "</tbody></table></div>"

    html += "</div>"

    # Add member form
    html += f"""
    <div class="form-card">
        <h3>添加成员</h3>
        <form action="/admin/teams/{team.id}/members/add" method="post">
            <div class="form-row">
                <div class="form-group">
                    <label>选择用户</label>
                    <select name="user_id" required>
                        <option value="">-- 请选择 --</option>
    """
    for u in available_users:
        label = f"#{u.id} {u.name or '(无名)'}"
        if u.phone:
            label += f" ({u.phone})"
        html += f'<option value="{u.id}">{label}</option>\n'

    html += """
                    </select>
                </div>
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


# ---- Main dashboard page ----


@router.get("", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    msg: str = Query(default=""),
    msg_type: str = Query(default="success"),
    db: AsyncSession = Depends(get_db),
):
    stats = await admin_stats(db)
    teams_resp = await admin_teams(db)
    teams = teams_resp["teams"]
    users_resp = await admin_users(db)
    users = users_resp["users"]
    txs_resp = await admin_transactions(db)
    transactions = txs_resp["transactions"]
    chats_resp = await admin_chat_messages(db)
    messages = chats_resp["messages"]
    files_resp = await admin_files(db)
    files = files_resp["files"]

    html = _page_head("管理后台")
    html += _alert(msg, msg_type)

    # Stats
    html += f"""
    <div class="section" id="stats">
        <h2>数据库统计</h2>
        <div class="stats">
            <div class="stat-card"><h3>用户数</h3><div class="value">{stats['user_count']}</div></div>
            <div class="stat-card"><h3>团队数</h3><div class="value">{stats['team_count']}</div></div>
            <div class="stat-card"><h3>交易记录</h3><div class="value">{stats['transaction_count']}</div></div>
            <div class="stat-card"><h3>聊天消息</h3><div class="value">{stats['chat_message_count']}</div></div>
            <div class="stat-card"><h3>文件数</h3><div class="value">{stats['file_count']}</div></div>
        </div>
    </div>
    """

    # Teams section with management
    html += f"""
    <div class="section" id="teams">
        {_section_heading("团队管理", len(teams))}

        <div class="form-card">
            <h3>创建新团队</h3>
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

        <div class="{_scroll_table_class(len(teams))}">
        <table>
            <thead><tr>
                <th>ID</th><th>团队名称</th><th>邀请码</th><th>成员数</th><th>交易笔数</th><th>创建时间</th><th>操作</th>
            </tr></thead>
            <tbody>
    """
    for t in teams:
        html += (
            f"<tr>"
            f"<td>{t['id']}</td>"
            f"<td>{t['name']}</td>"
            f"<td><code>{t['invite_code']}</code></td>"
            f"<td>{t['member_count']}</td>"
            f"<td>{t['transaction_count']}</td>"
            f"<td>{t['created_at']}</td>"
            f"<td>"
            f"<div class='actions'>"
            f"<a href='/admin/teams/{t['id']}' class='btn btn-primary btn-sm'>管理成员</a>"
            f"<form action='/admin/teams/{t['id']}/regenerate-code' method='post'>"
            f"<button type='submit' class='btn btn-outline btn-sm'>新邀请码</button>"
            f"</form>"
            f"<form action='/admin/teams/{t['id']}/delete' method='post' "
            f"onsubmit=\"return confirm('确定要删除团队「{t['name']}」吗？将清除所有关联数据。')\">"
            f"<button type='submit' class='btn btn-danger btn-sm'>删除</button>"
            f"</form>"
            f"</div>"
            f"</td>"
            f"</tr>"
        )
    html += "</tbody></table></div></div>"

    # Users
    users_table_class = _scroll_table_class(len(users))
    html += f"""
    <div class="section" id="users">
        {_section_heading("用户列表", len(users))}
        <div class="{users_table_class}">
        <table>
            <thead><tr><th>ID</th><th>名称</th><th>手机</th><th>OpenID</th><th>角色</th><th>团队</th><th>创建时间</th></tr></thead>
            <tbody>
    """
    for u in users:
        role = u["role"] or "member"
        html += (
            f"<tr><td>{u['id']}</td><td>{u['name']}</td><td>{u['phone'] or '-'}</td>"
            f"<td>{u['open_id'] or '-'}</td><td><span class='label {role}'>{role}</span></td>"
            f"<td>{u['team_name'] or '-'}</td><td>{u['created_at']}</td></tr>"
        )
    html += "</tbody></table></div></div>"

    # Transactions
    txs_table_class = _scroll_table_class(len(transactions))
    html += f"""
    <div class="section" id="transactions">
        {_section_heading("最近交易", len(transactions))}
        <div class="{txs_table_class}">
        <table>
            <thead><tr><th>ID</th><th>团队</th><th>类型</th><th>金额</th><th>类别</th><th>描述</th><th>产品</th><th>交易日期</th></tr></thead>
            <tbody>
    """
    for t in transactions:
        label_class = t["type"]
        type_label = "收入" if t["type"] == "income" else "支出"
        html += (
            f"<tr><td>{t['id']}</td><td>{t['team_id']}</td>"
            f"<td><span class='label {label_class}'>{type_label}</span></td>"
            f"<td>¥{t['amount']:.2f}</td><td>{t['category']}</td>"
            f"<td>{t['description'] or '-'}</td><td>{t['product'] or '-'}</td>"
            f"<td>{t['transaction_date']}</td></tr>"
        )
    html += "</tbody></table></div></div>"

    # Chat messages
    html += """
    <div class="section" id="chats">
        <h2>最近聊天</h2>
        <table>
            <thead><tr><th>ID</th><th>角色</th><th>内容预览</th><th>时间</th></tr></thead>
            <tbody>
    """
    for m in messages:
        html += f"<tr><td>{m['id']}</td><td><span class='label {m['role']}'>{m['role']}</span></td><td>{m['content_preview']}</td><td>{m['created_at']}</td></tr>"
    html += "</tbody></table></div>"

    # Files
    html += """
    <div class="section" id="files">
        <h2>文件列表</h2>
        <table>
            <thead><tr><th>ID</th><th>文件名</th><th>URL</th><th>时间</th></tr></thead>
            <tbody>
    """
    for f in files:
        html += f"<tr><td>{f['id']}</td><td>{f['filename']}</td><td>{f['url']}</td><td>{f['created_at']}</td></tr>"
    html += "</tbody></table></div>"

    html += _PAGE_TAIL
    return HTMLResponse(content=html)
