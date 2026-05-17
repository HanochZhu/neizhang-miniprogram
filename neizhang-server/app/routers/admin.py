from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.team import Team
from app.models.transaction import Transaction
from app.models.chat_message import ChatMessage
from app.models.file_record import FileRecord

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


@router.get("/api/v1/admin/stats")
async def admin_stats(db: AsyncSession = Depends(get_db)):
    """Return database statistics as JSON."""
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
    """Return all teams with member and transaction counts."""
    teams_result = await db.execute(select(Team).order_by(Team.created_at.desc()))
    teams = teams_result.scalars().all()

    member_rows = await db.execute(
        select(User.team_id, sa_func.count(User.id))
        .where(User.team_id.isnot(None))
        .group_by(User.team_id)
    )
    member_counts = {row[0]: row[1] for row in member_rows.all()}

    tx_rows = await db.execute(
        select(Transaction.team_id, sa_func.count(Transaction.id)).group_by(
            Transaction.team_id
        )
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
    """Return all users with team info."""
    result = await db.execute(
        select(User, Team)
        .outerjoin(Team, User.team_id == Team.id)
        .order_by(User.created_at.desc())
    )
    rows = result.all()
    users = []
    for user, team in rows:
        users.append(
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
        )
    return {"users": users}


@router.get("/api/v1/admin/transactions")
async def admin_transactions(
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
):
    """Return recent transactions."""
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
                "transaction_date": t.transaction_date.isoformat()
                if t.transaction_date
                else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in transactions
        ],
        "total_returned": len(transactions),
    }


@router.get("/api/v1/admin/chat-messages")
async def admin_chat_messages(db: AsyncSession = Depends(get_db)):
    """Return recent chat messages."""
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
    """Return file records."""
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


@router.get("")
async def admin_page(db: AsyncSession = Depends(get_db)):
    """Simple HTML admin dashboard page."""
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

    teams_table_class = _scroll_table_class(len(teams))
    users_table_class = _scroll_table_class(len(users))
    txs_table_class = _scroll_table_class(len(transactions))

    html = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>内账 Admin Panel</title>
        <style>{ADMIN_STYLES}</style>
    </head>
    <body>
        <h1>内账管理后台</h1>
        <nav class="nav">
            <a href="#stats">统计</a>
            <a href="#teams">团队管理</a>
            <a href="#users">用户</a>
            <a href="#transactions">最近交易</a>
            <a href="#chats">聊天</a>
            <a href="#files">文件</a>
        </nav>

        <div class="section" id="stats">
            <h2>数据库统计</h2>
            <div class="stats">
                <div class="stat-card"><h3>用户数</h3><div class="value">{stats["user_count"]}</div></div>
                <div class="stat-card"><h3>团队数</h3><div class="value">{stats["team_count"]}</div></div>
                <div class="stat-card"><h3>交易记录</h3><div class="value">{stats["transaction_count"]}</div></div>
                <div class="stat-card"><h3>聊天消息</h3><div class="value">{stats["chat_message_count"]}</div></div>
                <div class="stat-card"><h3>文件数</h3><div class="value">{stats["file_count"]}</div></div>
            </div>
        </div>

        <div class="section" id="teams">
            {_section_heading("团队管理", len(teams))}
            <div class="{teams_table_class}">
            <table>
                <thead><tr><th>ID</th><th>团队名称</th><th>邀请码</th><th>成员数</th><th>交易笔数</th><th>创建时间</th></tr></thead>
                <tbody>
    """
    for t in teams:
        html += (
            f"<tr><td>{t['id']}</td><td>{t['name']}</td><td><code>{t['invite_code']}</code></td>"
            f"<td>{t['member_count']}</td><td>{t['transaction_count']}</td><td>{t['created_at']}</td></tr>"
        )

    html += f"""
                </tbody>
            </table>
            </div>
        </div>

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

    html += f"""
                </tbody>
            </table>
            </div>
        </div>

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

    html += """
                </tbody>
            </table>
            </div>
        </div>

        <div class="section" id="chats">
            <h2>最近聊天</h2>
            <table>
                <thead><tr><th>ID</th><th>角色</th><th>内容预览</th><th>时间</th></tr></thead>
                <tbody>
    """
    for m in messages:
        html += f"<tr><td>{m['id']}</td><td><span class='label {m['role']}'>{m['role']}</span></td><td>{m['content_preview']}</td><td>{m['created_at']}</td></tr>"

    html += """
                </tbody>
            </table>
        </div>

        <div class="section" id="files">
            <h2>文件列表</h2>
            <table>
                <thead><tr><th>ID</th><th>文件名</th><th>URL</th><th>时间</th></tr></thead>
                <tbody>
    """
    for f in files:
        html += f"<tr><td>{f['id']}</td><td>{f['filename']}</td><td>{f['url']}</td><td>{f['created_at']}</td></tr>"

    html += """
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
