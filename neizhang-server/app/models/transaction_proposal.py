import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, ForeignKey, Integer, Text, Float
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class TransactionProposal(Base):
    """待用户确认的记账提案（大模型不确定时生成）。"""

    __tablename__ = "transaction_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    product: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    transaction_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=func.now())
