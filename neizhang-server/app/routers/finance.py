from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.transaction import Transaction
from app.models.user import User
from app.routers.auth import get_current_user
from app.utils.dates import parse_end_date_exclusive, parse_start_date

router = APIRouter(prefix="/api/v1/finance", tags=["finance"])


@router.get("/summary")
async def get_finance_summary(
    scope: str = Query("team", description="范围: team 或 personal"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    tx_limit: int = Query(
        100,
        ge=1,
        le=500,
        description="交易记录列表返回条数上限（汇总统计仍含全部）",
    ),
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

    # Recent transactions（列表有上限；收入/支出合计与 transaction_count 为区间内全部）
    tx_query = (
        select(Transaction)
        .where(*base_conditions)
        .order_by(
            Transaction.transaction_date.desc(),
            Transaction.id.desc(),
        )
        .limit(tx_limit)
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
        "transactions_limit": tx_limit,
        "transactions_returned": len(tx_list),
        "by_category": by_category,
        "transactions": tx_list,
    }


@router.delete("/transactions/{transaction_id}")
async def delete_transaction(
    transaction_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a transaction. Only team admins can do this."""
    user_id = current_user.get("user_id")
    team_id = current_user.get("team_id")

    if not team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Team not found"
        )

    # Check user is admin
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None or user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有团队管理员可以删除记账数据",
        )

    # Find transaction and verify it belongs to the team
    tx_result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    )
    tx = tx_result.scalar_one_or_none()
    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="交易记录不存在",
        )
    if tx.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无法删除其他团队的记账数据",
        )

    await db.delete(tx)
    await db.flush()

    return {"success": True, "message": "已删除"}


class UpdateTransactionRequest(BaseModel):
    type: Optional[str] = Field(default=None, pattern="^(income|expense)$")
    amount: Optional[float] = Field(default=None, gt=0)
    category: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None, max_length=500)
    product: Optional[str] = Field(default=None, max_length=100)
    transaction_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.put("/transactions/{transaction_id}")
async def update_transaction(
    transaction_id: int,
    request: UpdateTransactionRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a transaction. Only team admins can do this."""
    user_id = current_user.get("user_id")
    team_id = current_user.get("team_id")

    if not team_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Team not found")

    # Check user is admin
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None or user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有团队管理员可以修改记账数据",
        )

    # Find transaction and verify it belongs to the team
    tx_result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    )
    tx = tx_result.scalar_one_or_none()
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="交易记录不存在")
    if tx.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="无法修改其他团队的记账数据"
        )

    # Apply updates
    if request.type is not None:
        tx.type = request.type
    if request.amount is not None:
        tx.amount = request.amount
    if request.category is not None:
        tx.category = request.category
    if request.description is not None:
        tx.description = request.description
    if request.product is not None:
        tx.product = request.product
    if request.transaction_date is not None:
        tx.transaction_date = datetime.strptime(request.transaction_date, "%Y-%m-%d")

    await db.flush()

    return {
        "success": True,
        "message": "已更新",
        "transaction": {
            "id": tx.id,
            "type": tx.type,
            "amount": tx.amount,
            "category": tx.category,
            "description": tx.description,
            "product": tx.product,
            "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
        },
    }
