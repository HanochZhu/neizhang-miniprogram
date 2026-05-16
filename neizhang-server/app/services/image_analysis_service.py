import base64
import json
import logging
import os
import re
from typing import Any, AsyncGenerator, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.file_record import FileRecord
from app.services.chat_service import (
    _extra_events_after_tool,
    _format_sse,
    _parse_tool_result,
    _save_message,
)
from app.tools.finance_tools import propose_transaction

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

VISION_JSON_PROMPT = (
    "你是财务截图识别助手。用户上传的图片可能是微信支付、支付宝、银行转账、收款通知等截图。\n"
    "请判断是否为支付/收款/转账类财务截图，并提取记账字段。\n"
    "只输出一个 JSON 对象，不要 markdown 代码块，格式如下：\n"
    '{"is_financial":true,"type":"expense","amount":50.0,"category":"餐饮",'
    '"description":"商户名或备注","transaction_date":"YYYY-MM-DD",'
    '"summary":"给用户的中文说明","reason":"识别依据"}\n'
    "若非财务截图："
    '{"is_financial":false,"summary":"说明原因","reason":""}\n'
    "规则：type 只能是 expense 或 income；amount 为正数；无法确定日期可省略 transaction_date。"
)


def _guess_mime(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return MIME_BY_EXT.get(ext, "image/jpeg")


def _is_image_file(filename: str) -> bool:
    ext = os.path.splitext(filename or "")[1].lower()
    return ext in IMAGE_EXTENSIONS


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return {}


async def _call_vision_api(image_b64: str, media_type: str) -> dict:
    """Call DeepSeek OpenAI-compatible API with image input."""
    base = (settings.deepseek_openai_base_url or "https://api.deepseek.com").rstrip("/")
    url = f"{base}/v1/chat/completions"
    payload = {
        "model": settings.deepseek_vision_model,
        "messages": [
            {"role": "system", "content": VISION_JSON_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_b64}",
                        },
                    },
                    {
                        "type": "text",
                        "text": "请分析这张图片并仅返回 JSON。",
                    },
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    choices = data.get("choices") or []
    if not choices:
        return {}
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    return _extract_json(content)


async def _load_image_file(
    file_id: int,
    team_id: int,
    user_id: int,
    db: AsyncSession,
) -> tuple[FileRecord, bytes, str]:
    result = await db.execute(
        select(FileRecord).where(
            FileRecord.id == file_id,
            FileRecord.team_id == team_id,
            FileRecord.user_id == user_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise ValueError("未找到该文件或无权访问")
    if not _is_image_file(record.filename):
        raise ValueError("仅支持分析图片文件（jpg/png/gif/webp 等）")
    if not os.path.isfile(record.storage_path):
        raise ValueError("文件不存在或已被删除")
    with open(record.storage_path, "rb") as f:
        content = f.read()
    if not content:
        raise ValueError("图片文件为空")
    return record, content, _guess_mime(record.filename)


async def analyze_image_stream(
    file_id: int,
    team_id: int,
    user_id: int,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """识别支付/收款截图并发起待确认记账提案（SSE）。"""
    if not (settings.deepseek_api_key or "").strip():
        yield _format_sse(
            {
                "type": "error",
                "content": "服务端未配置 DEEPSEEK_API_KEY，无法识别图片。",
            }
        )
        yield _format_sse({"type": "message_stop"})
        return

    yield _format_sse({"type": "text_delta", "content": "正在识别图片…\n"})

    try:
        record, raw, media_type = await _load_image_file(file_id, team_id, user_id, db)
    except ValueError as e:
        yield _format_sse({"type": "error", "content": str(e)})
        yield _format_sse({"type": "message_stop"})
        return

    await _save_message(
        db,
        team_id,
        user_id,
        "user",
        f"[上传图片] {record.filename}",
    )

    image_b64 = base64.standard_b64encode(raw).decode("ascii")
    try:
        parsed = await _call_vision_api(image_b64, media_type)
    except httpx.HTTPStatusError as e:
        logger.warning("vision API HTTP error: %s", e)
        msg = "图片识别服务暂时不可用，请稍后重试或改用文字描述记账。"
        yield _format_sse({"type": "text_delta", "content": msg})
        await _save_message(db, team_id, user_id, "assistant", msg)
        yield _format_sse({"type": "message_stop"})
        return
    except Exception as e:
        logger.exception("vision API failed")
        msg = f"图片识别失败：{e}"
        yield _format_sse({"type": "error", "content": msg})
        yield _format_sse({"type": "message_stop"})
        return

    if not parsed.get("is_financial"):
        summary = (
            parsed.get("summary")
            or "这张图片看起来不是支付或收款截图，暂未生成记账提案。"
        )
        yield _format_sse({"type": "text_delta", "content": summary})
        await _save_message(db, team_id, user_id, "assistant", summary)
        yield _format_sse({"type": "message_stop"})
        return

    tx_type = parsed.get("type")
    amount = parsed.get("amount")
    category = (parsed.get("category") or "").strip() or "其他"
    if tx_type not in ("income", "expense"):
        summary = parsed.get("summary") or "无法判断是收入还是支出，请补充说明后再试。"
        yield _format_sse({"type": "text_delta", "content": summary})
        await _save_message(db, team_id, user_id, "assistant", summary)
        yield _format_sse({"type": "message_stop"})
        return

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = 0.0

    if amount <= 0:
        summary = parsed.get("summary") or "未能从截图中识别有效金额，请手动输入记账信息。"
        yield _format_sse({"type": "text_delta", "content": summary})
        await _save_message(db, team_id, user_id, "assistant", summary)
        yield _format_sse({"type": "message_stop"})
        return

    reason = (
        parsed.get("reason")
        or parsed.get("summary")
        or f"根据截图识别为{'收入' if tx_type == 'income' else '支出'}"
    )
    description = parsed.get("description")
    transaction_date = parsed.get("transaction_date")

    tool_result = await propose_transaction(
        team_id=team_id,
        user_id=user_id,
        tx_type=tx_type,
        amount=amount,
        category=category,
        reason=reason,
        description=description,
        transaction_date=transaction_date,
        db=db,
    )
    await db.commit()

    data = _parse_tool_result(tool_result)
    if not data.get("pending"):
        err = data.get("error", "创建记账提案失败")
        yield _format_sse({"type": "error", "content": err})
        yield _format_sse({"type": "message_stop"})
        return

    summary = data.get("message", "请确认是否保存该笔记录")
    yield _format_sse(
        {
            "type": "tool_result",
            "tool_name": "propose_transaction",
            "content": tool_result,
        }
    )
    for extra in _extra_events_after_tool("propose_transaction", tool_result):
        yield _format_sse(extra)
    await _save_message(db, team_id, user_id, "assistant", summary)
    yield _format_sse({"type": "message_stop"})
