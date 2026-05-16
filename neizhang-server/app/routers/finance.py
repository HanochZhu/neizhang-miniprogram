from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.transaction import Transaction
from app.routers.auth import get_current_user
from app.utils.dates import parse_end_date_exclusive, parse_start_date

router = APIRouter(prefix="/api/v1/finance", tags=["finance"])


@router.get("/summary")
async def get_finance_summary(
    scope: str = Query("team", description="范围: team 或 personal"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a financial summary with income/expense totals and breakdown by category."""
    user_id = current_user.get("user_id")
    team_id = current_user.get("team_id")

    if not team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Team not found",
        )

    # Build base conditions
    base_conditions = [Transaction.team_id == team_id]
    if scope == "personal" and user_id:
        base_conditions.append(Transaction.user_id == user_id)
    if start_date:
        try:
            base_conditions.append(
                Transaction.transaction_date >= parse_start_date(start_date)
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date 格式应为 YYYY-MM-DD",
            )
    if end_date:
        try:
            base_conditions.append(
                Transaction.transaction_date < parse_end_date_exclusive(end_date)
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="end_date 格式应为 YYYY-MM-DD",
            )

    # Income total
    income_result = await db.execute(
        select(sa_func.coalesce(sa_func.sum(Transaction.amount), 0.0)).where(
            Transaction.type == "income", *base_conditions
        )
    )
    income_total = float(income_result.scalar() or 0.0)

    # Expense total
    expense_result = await db.execute(
        select(sa_func.coalesce(sa_func.sum(Transaction.amount), 0.0)).where(
            Transaction.type == "expense", *base_conditions
        )
    )
    expense_total = float(expense_result.scalar() or 0.0)

    # Total count
    count_result = await db.execute(
        select(sa_func.count(Transaction.id)).where(*base_conditions)
    )
    tx_count = count_result.scalar() or 0

    # By category
    category_result = await db.execute(
        select(
            Transaction.category,
            sa_func.sum(Transaction.amount),
            sa_func.count(Transaction.id),
        )
        .where(*base_conditions)
        .group_by(Transaction.category)
        .order_by(sa_func.sum(Transaction.amount).desc())
    )
    by_category = [
        {"category": row[0], "amount": float(row[1]), "count": row[2]}
        for row in category_result.all()
    ]

    # Recent transactions
    tx_query = (
        select(Transaction)
        .where(*base_conditions)
        .order_by(Transaction.transaction_date.desc())
        .limit(20)
    )
    tx_result = await db.execute(tx_query)
    transactions = tx_result.scalars().all()

    tx_list = [
        {
            "id": t.id,
            "type": t.type,
            "category": t.category,
            "amount": t.amount,
            "description": t.description,
            "product": t.product,
            "user_id": t.user_id,
            "transaction_date": t.transaction_date.isoformat(),
            "created_at": t.created_at.isoformat(),
        }
        for t in transactions
    ]

    return {
        "income_total": income_total,
        "expense_total": expense_total,
        "balance": income_total - expense_total,
        "transaction_count": tx_count,
        "by_category": by_category,
        "transactions": tx_list,
    }
