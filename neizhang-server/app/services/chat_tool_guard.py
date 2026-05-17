"""限制单次对话中的记账工具调用，避免根据历史聊天记录批量重复入账。"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

# 用户要求「整段历史重新记账」类表述
_BULK_RERECORD_RE = re.compile(
    r"(全部|所有|整批|批量).{0,8}(重新?记|重记|再记|补记)"
    r"|重新?记.{0,8}(全部|所有|之前|上面|历史)"
    r"|补记.{0,8}(全部|所有)"
    r"|把.{0,12}(重新?记|再记|补记)"
)

_AMOUNT_RE = re.compile(
    r"(?:¥|￥)\s*\d+(?:\.\d+)?"
    r"|\d+(?:\.\d+)?\s*(?:元|块|块钱)"
)


def is_bulk_rerecord_intent(user_message: str) -> bool:
    text = (user_message or "").strip()
    if not text:
        return False
    return bool(_BULK_RERECORD_RE.search(text))


def count_explicit_booking_items_in_message(user_message: str) -> int:
    """当前用户句子里明确出现的金额条数（用于允许多笔记账的上限）。"""
    return len(_AMOUNT_RE.findall(user_message or ""))


def max_add_transactions_allowed(user_message: str) -> int:
    if is_bulk_rerecord_intent(user_message):
        return 0
    explicit = count_explicit_booking_items_in_message(user_message)
    return max(1, explicit)


def check_add_transaction_allowed(
    user_message: str,
    add_count_so_far: int,
) -> Optional[str]:
    """若不允许再调用 add_transaction，返回错误说明 JSON 字符串。"""
    limit = max_add_transactions_allowed(user_message)
    if add_count_so_far >= limit:
        if limit == 0:
            return json.dumps(
                {
                    "error": (
                        "「全部重新记录」等批量指令不能根据聊天记录自动逐条入账。"
                        "请先使用 query_transactions 查看已记账目；"
                        "若需补记，请在本条消息中逐条写明金额与类别，或一次只记一笔。"
                    ),
                    "blocked": True,
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "error": (
                    f"本条消息最多直接入账 {limit} 笔（与句中明确金额数量一致）。"
                    "请勿根据更早的聊天记录批量记账；"
                    "其余条目请让用户在新消息中分别说明，或使用 propose_transaction 单笔确认。"
                ),
                "blocked": True,
            },
            ensure_ascii=False,
        )
    return None


def make_tool_guard(user_message: str) -> dict[str, Any]:
    return {"user_message": user_message, "add_count": 0}
