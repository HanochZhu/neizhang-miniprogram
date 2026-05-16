import json
from datetime import datetime, date
from typing import Optional

from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.models.transaction_proposal import TransactionProposal


async def propose_transaction(
    team_id: int,
    user_id: int,
    tx_type: str,
    amount: float,
    category: str,
    reason: str,
    description: Optional[str] = None,
    product: Optional[str] = None,
    transaction_date: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> str:
    """创建待确认的记账提案，不直接写入账目表。"""
    if db is None:
        return json.dumps({"error": "数据库连接不可用"}, ensure_ascii=False)

    if tx_type not in ("income", "expense"):
        return json.dumps({"error": "类型必须是 income 或 expense"}, ensure_ascii=False)

    if amount <= 0:
        return json.dumps({"error": "金额必须大于0"}, ensure_ascii=False)

    if transaction_date:
        try:
            datetime.strptime(transaction_date, "%Y-%m-%d")
        except ValueError:
            return json.dumps(
                {"error": "日期格式错误，应为 YYYY-MM-DD"}, ensure_ascii=False
            )

    proposal = TransactionProposal(
        team_id=team_id,
        user_id=user_id,
        type=tx_type,
        amount=amount,
        category=category,
        description=description,
        product=product,
        transaction_date=transaction_date,
        reason=reason,
        status="pending",
    )
    db.add(proposal)
    await db.flush()

    type_label = "收入" if tx_type == "income" else "支出"
    summary = f"{type_label} ¥{amount:.2f}，类别：{category}"
    if product:
        summary += f"，项目：{product}"
    if description:
        summary += f"，备注：{description}"
    if transaction_date:
        summary += f"，日期：{transaction_date}"

    return json.dumps(
        {
            "success": True,
            "pending": True,
            "proposal_id": proposal.id,
            "message": f"请确认是否保存：{summary}",
            "reason": reason,
            "transaction": {
                "type": tx_type,
                "amount": amount,
                "category": category,
                "description": description,
                "product": product,
                "transaction_date": transaction_date,
            },
        },
        ensure_ascii=False,
    )


async def add_transaction(
    team_id: int,
    user_id: int,
    tx_type: str,
    amount: float,
    category: str,
    description: Optional[str] = None,
    product: Optional[str] = None,
    transaction_date: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> str:
    """Add a transaction record to the database.

    Returns a JSON string with success info or error.
    """
    if db is None:
        return json.dumps({"error": "数据库连接不可用"}, ensure_ascii=False)

    if tx_type not in ("income", "expense"):
        return json.dumps({"error": "类型必须是 income 或 expense"}, ensure_ascii=False)

    if amount <= 0:
        return json.dumps({"error": "金额必须大于0"}, ensure_ascii=False)

    tx_date: datetime
    if transaction_date:
        try:
            parsed = datetime.strptime(transaction_date, "%Y-%m-%d")
            tx_date = parsed
        except ValueError:
            return json.dumps(
                {"error": "日期格式错误，应为 YYYY-MM-DD"}, ensure_ascii=False
            )
    else:
        tx_date = datetime.now()

    transaction = Transaction(
        team_id=team_id,
        user_id=user_id,
        type=tx_type,
        amount=amount,
        category=category,
        description=description,
        product=product,
        transaction_date=tx_date,
    )
    db.add(transaction)
    await db.flush()

    type_label = "收入" if tx_type == "income" else "支出"
    return json.dumps(
        {
            "success": True,
            "message": f"已记录{type_label}：¥{amount:.2f}，类别：{category}",
            "transaction_id": transaction.id,
        },
        ensure_ascii=False,
    )


async def query_transactions(
    team_id: int,
    user_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    product: Optional[str] = None,
    tx_type: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> str:
    """Query transactions with optional filters.

    Returns a formatted string with the matching records.
    """
    if db is None:
        return json.dumps({"error": "数据库连接不可用"}, ensure_ascii=False)

    query = select(Transaction).where(Transaction.team_id == team_id)

    if user_id is not None:
        query = query.where(Transaction.user_id == user_id)
    if start_date:
        query = query.where(Transaction.transaction_date >= datetime.strptime(start_date, "%Y-%m-%d"))
    if end_date:
        query = query.where(Transaction.transaction_date <= datetime.strptime(end_date, "%Y-%m-%d"))
    if category:
        query = query.where(Transaction.category == category)
    if product:
        query = query.where(Transaction.product == product)
    if tx_type:
        query = query.where(Transaction.type == tx_type)

    query = query.order_by(Transaction.transaction_date.desc()).limit(50)

    result = await db.execute(query)
    transactions = result.scalars().all()

    if not transactions:
        return "没有找到匹配的收支记录。"

    lines = [f"找到 {len(transactions)} 条记录："]
    for t in transactions:
        type_label = "收入" if t.type == "income" else "支出"
        date_str = t.transaction_date.strftime("%Y-%m-%d")
        desc = f" - {t.description}" if t.description else ""
        prod = f" [{t.product}]" if t.product else ""
        lines.append(
            f"  {date_str} {type_label} ¥{t.amount:.2f} ({t.category}){prod}{desc}"
        )

    income_total = sum(t.amount for t in transactions if t.type == "income")
    expense_total = sum(t.amount for t in transactions if t.type == "expense")
    lines.append(f"--- 小计：收入 ¥{income_total:.2f}，支出 ¥{expense_total:.2f}")

    return "\n".join(lines)


async def get_summary(
    team_id: int,
    user_id: Optional[int] = None,
    scope: str = "team",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> str:
    """Get a financial summary (income/expense totals) for a team or personal scope.

    Returns a formatted string.
    """
    if db is None:
        return json.dumps({"error": "数据库连接不可用"}, ensure_ascii=False)

    base_cond = [Transaction.team_id == team_id]
    if scope == "personal" and user_id is not None:
        base_cond.append(Transaction.user_id == user_id)
    if start_date:
        base_cond.append(Transaction.transaction_date >= datetime.strptime(start_date, "%Y-%m-%d"))
    if end_date:
        base_cond.append(Transaction.transaction_date <= datetime.strptime(end_date, "%Y-%m-%d"))

    # Income total
    income_query = select(sa_func.coalesce(sa_func.sum(Transaction.amount), 0.0)).where(
        Transaction.type == "income", *base_cond
    )
    income_result = await db.execute(income_query)
    income_total = income_result.scalar() or 0.0

    # Expense total
    expense_query = select(sa_func.coalesce(sa_func.sum(Transaction.amount), 0.0)).where(
        Transaction.type == "expense", *base_cond
    )
    expense_result = await db.execute(expense_query)
    expense_total = expense_result.scalar() or 0.0

    # Count
    count_query = select(sa_func.count(Transaction.id)).where(*base_cond)
    count_result = await db.execute(count_query)
    tx_count = count_result.scalar() or 0

    balance = income_total - expense_total
    scope_label = "个人" if scope == "personal" else "团队"

    return (
        f"【{scope_label}财务汇总】\n"
        f"  总收入：¥{income_total:.2f}\n"
        f"  总支出：¥{expense_total:.2f}\n"
        f"  结余：¥{balance:.2f}\n"
        f"  交易笔数：{tx_count}"
    )
