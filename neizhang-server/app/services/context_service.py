from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_message import ChatMessage


def _normalize_content(content) -> str:
    if content is None:
        return ""
    return str(content).strip()


def deduplicate_messages(messages: list) -> list:
    """去掉相邻且 role、content 相同的消息（用于读库后的上下文）。"""
    if not messages:
        return []
    deduped = [messages[0]]
    for msg in messages[1:]:
        prev = deduped[-1]
        if prev.get("role") == msg.get("role") and _normalize_content(
            prev.get("content")
        ) == _normalize_content(msg.get("content")):
            continue
        deduped.append(msg)
    return deduped


def append_user_message(messages: list, user_message: str) -> list:
    """拼入本轮用户消息；若历史末尾已是同内容用户消息则不再追加。"""
    content = _normalize_content(user_message)
    result = list(messages)
    if (
        result
        and result[-1].get("role") == "user"
        and _normalize_content(result[-1].get("content")) == content
    ):
        return result
    result.append({"role": "user", "content": content})
    return result


async def get_last_team_message(
    team_id: int,
    db: AsyncSession,
) -> Optional[ChatMessage]:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.team_id == team_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def is_duplicate_of_last_message(
    team_id: int,
    role: str,
    content: str,
    db: AsyncSession,
) -> bool:
    """是否与团队最新一条消息的 role、content 相同。"""
    text = _normalize_content(content)
    last = await get_last_team_message(team_id, db)
    if not last:
        return False
    return last.role == role and _normalize_content(last.content) == text


def estimate_tokens(messages: list) -> int:
    """Roughly estimate token count (~4 characters per token)."""
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "content" in block.get("text", block):
                    total_chars += len(str(block.get("text", block.get("content", ""))))
                else:
                    total_chars += len(str(block))
        else:
            total_chars += len(str(content))
    return total_chars // 4


async def get_recent_messages(
    team_id: int,
    db: AsyncSession,
    limit: int = 20,
) -> list:
    """Get the most recent chat messages for a team.

    Returns a list of dicts formatted for the anthropic messages API.
    """
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.team_id == team_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    messages = list(reversed(result.scalars().all()))

    formatted = []
    for msg in messages:
        entry = {"role": msg.role, "content": msg.content}
        formatted.append(entry)

    return deduplicate_messages(formatted)


async def compress_context(team_id: int, db: AsyncSession) -> Optional[str]:
    """Compress old chat context.

    This is a placeholder that returns None.
    In a production system, this would use the LLM to summarize older messages.
    """
    # Get total message count for this team
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.team_id == team_id).order_by(ChatMessage.created_at.desc())
    )
    all_messages = list(reversed(result.scalars().all()))

    if len(all_messages) <= 30:
        return None

    # Mark old messages as compressed (placeholder - real LLM-based compression would go here)
    old_messages = all_messages[:-20]
    summary = (
        f"之前有 {len(old_messages)} 条历史消息已被压缩。"
        f"这些消息涉及早期的财务讨论和记录。"
    )

    return summary
