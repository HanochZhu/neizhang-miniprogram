import json
import logging
from typing import AsyncGenerator, Optional

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.chat_message import ChatMessage
from app.services.context_service import get_recent_messages
from app.tools.finance_tools import add_transaction, query_transactions, get_summary

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是内账助手，一个专注于财务记账和费用管理的AI助手。"
    "你只能回答与财务、记账、费用管理相关的问题。"
    "如果用户询问与财务无关的问题，请礼貌地告知你只能帮助处理财务相关的事务，并引导用户回到记账话题。\n\n"
    "你可以使用以下工具来帮助用户管理财务：\n"
    "- add_transaction: 添加一笔收支记录\n"
    "- query_transactions: 查询收支记录\n"
    "- get_summary: 获取财务汇总\n\n"
    "请始终使用中文回复。\n\n"
    "重要规则：\n"
    "1. 每次用户要求记一笔新的收支（即使品类、金额与之前相同），都必须调用 add_transaction 新增一条记录；"
    "不要因对话历史中已有类似账目而跳过记账。\n"
    "2. 调用 add_transaction 成功后，用一句话向用户确认已记账（包含金额与类别）。\n"
    "3. 信息不明确时先简短追问，明确后立刻调用工具。"
)

TOOLS = [
    {
        "name": "add_transaction",
        "description": "添加一笔收支记录",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["income", "expense"],
                    "description": "类型：收入或支出",
                },
                "amount": {"type": "number", "description": "金额（元）"},
                "category": {
                    "type": "string",
                    "description": "类别，如：餐饮、交通、工资、办公用品等",
                },
                "description": {
                    "type": "string",
                    "description": "描述（可选）",
                },
                "product": {
                    "type": "string",
                    "description": "产品/项目名称（可选）",
                },
                "transaction_date": {
                    "type": "string",
                    "description": "交易日期，格式YYYY-MM-DD（可选，默认为今天）",
                },
            },
            "required": ["type", "amount", "category"],
        },
    },
    {
        "name": "query_transactions",
        "description": "查询收支记录",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "开始日期 YYYY-MM-DD",
                },
                "end_date": {
                    "type": "string",
                    "description": "结束日期 YYYY-MM-DD",
                },
                "category": {"type": "string", "description": "按类别筛选"},
                "product": {
                    "type": "string",
                    "description": "按产品/项目筛选",
                },
                "type": {
                    "type": "string",
                    "enum": ["income", "expense"],
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_summary",
        "description": "获取财务汇总数据",
        "input_schema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["team", "personal"],
                    "description": "范围：团队或个人",
                },
                "start_date": {
                    "type": "string",
                    "description": "开始日期 YYYY-MM-DD",
                },
                "end_date": {
                    "type": "string",
                    "description": "结束日期 YYYY-MM-DD",
                },
            },
            "required": ["scope"],
        },
    },
]

aclient = AsyncAnthropic(
    base_url=settings.deepseek_base_url,
    api_key=settings.deepseek_api_key,
)


def _format_sse(data: dict) -> str:
    """Format a dict as an SSE data frame."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _extra_events_after_tool(tool_name: str, result: str) -> list[dict]:
    """SSE events to push after a tool finishes (e.g. confirm记账成功)."""
    events: list[dict] = []
    if tool_name != "add_transaction":
        return events
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return events
    if data.get("success") and data.get("message"):
        events.append({"type": "record_success", "content": data["message"]})
        events.append({"type": "text_delta", "content": data["message"]})
    return events


async def _execute_tool(
    tool_name: str,
    tool_input: dict,
    team_id: int,
    user_id: int,
    db: AsyncSession,
) -> str:
    """Execute a finance tool and return the result string."""
    if tool_name == "add_transaction":
        return await add_transaction(
            team_id=team_id,
            user_id=user_id,
            tx_type=tool_input.get("type", ""),
            amount=tool_input.get("amount", 0),
            category=tool_input.get("category", ""),
            description=tool_input.get("description"),
            product=tool_input.get("product"),
            transaction_date=tool_input.get("transaction_date"),
            db=db,
        )
    elif tool_name == "query_transactions":
        return await query_transactions(
            team_id=team_id,
            user_id=user_id,
            start_date=tool_input.get("start_date"),
            end_date=tool_input.get("end_date"),
            category=tool_input.get("category"),
            product=tool_input.get("product"),
            tx_type=tool_input.get("type"),
            db=db,
        )
    elif tool_name == "get_summary":
        return await get_summary(
            team_id=team_id,
            user_id=user_id,
            scope=tool_input.get("scope", "team"),
            start_date=tool_input.get("start_date"),
            end_date=tool_input.get("end_date"),
            db=db,
        )
    else:
        return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)


async def _save_message(
    db: AsyncSession,
    team_id: int,
    user_id: int,
    role: str,
    content: str,
) -> None:
    """Save a chat message to the database."""
    msg = ChatMessage(
        team_id=team_id,
        user_id=user_id,
        role=role,
        content=content,
    )
    db.add(msg)
    await db.flush()


async def chat_stream(
    team_id: int,
    user_id: int,
    user_message: str,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """SSE streaming chat with DeepSeek via the anthropic SDK.

    Implements a ReAct loop:
      1. Send messages (history + user message) to DeepSeek
      2. Stream the response text deltas
      3. If the response contains tool_use blocks, execute them and loop back
      4. When a pure text response is returned, end the stream
    """
    if not (settings.deepseek_api_key or "").strip():
        yield _format_sse(
            {
                "type": "error",
                "content": "服务端未配置 DEEPSEEK_API_KEY：请在 neizhang-server/.env 中设置后重启服务。",
            }
        )
        return

    # Load recent history
    history = await get_recent_messages(team_id, db, limit=20)
    messages = list(history)
    messages.append({"role": "user", "content": user_message})

    # Save the user message to DB
    await _save_message(db, team_id, user_id, "user", user_message)

    # Buffer for the full assistant response content blocks across turns
    all_assistant_content: list = []
    last_tool_results: list = []
    final_text_content: Optional[str] = None

    # ReAct loop (max 5 iterations to prevent infinite loops)
    for iteration in range(5):
        if settings.chat_trace:
            logger.info(
                "chat iteration=%s messages_len=%s",
                iteration,
                len(messages),
            )

        # Collect text deltas and tool usage from this iteration
        collected_text = ""
        collected_tool_uses = []
        current_tool_input_buffers: dict = {}

        async with aclient.messages.stream(
            model=settings.deepseek_model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        collected_tool_uses.append(block)
                        current_tool_input_buffers[block.id] = ""
                        # Notify the frontend that a tool was invoked
                        yield _format_sse(
                            {
                                "type": "tool_start",
                                "tool_name": block.name,
                                "tool_input": {},
                                "tool_use_id": block.id,
                            }
                        )

                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        collected_text += event.delta.text
                        yield _format_sse(
                            {
                                "type": "text_delta",
                                "content": event.delta.text,
                            }
                        )
                    elif event.delta.type == "input_json_delta":
                        tid = event.delta.partial_json
                        if tid and event.index < len(collected_tool_uses):
                            tool_id = collected_tool_uses[event.index].id
                            if tool_id in current_tool_input_buffers:
                                current_tool_input_buffers[tool_id] += tid

            # Get the final message from the stream
            final_message = await stream.get_final_message()
            assistant_content_blocks = final_message.content
            if settings.chat_trace:
                stop_reason = getattr(final_message, "stop_reason", None)
                block_types = [
                    getattr(b, "type", type(b).__name__)
                    for b in assistant_content_blocks
                ]
                logger.info(
                    "chat iteration=%s stop_reason=%s block_types=%s",
                    iteration,
                    stop_reason,
                    block_types,
                )

        # Check for tool use in the response
        tool_use_blocks = [b for b in assistant_content_blocks if b.type == "tool_use"]
        text_blocks = [b for b in assistant_content_blocks if b.type == "text"]

        # Collect all assistant content for saving to DB later
        all_assistant_content.append(assistant_content_blocks)

        # If there are no tool uses, we're done
        if not tool_use_blocks:
            final_text_content = collected_text or (text_blocks[0].text if text_blocks else "")
            if settings.chat_trace:
                logger.info(
                    "chat iteration=%s finished with text (len=%s)",
                    iteration,
                    len(final_text_content or ""),
                )
            break

        if settings.chat_trace:
            logger.info(
                "chat iteration=%s tool_round names=%s",
                iteration,
                [b.name for b in tool_use_blocks],
            )

        # We have tool uses: add the assistant response to messages
        messages.append({"role": "assistant", "content": assistant_content_blocks})

        # Execute each tool and add tool_result content
        for tool_use in tool_use_blocks:
            tool_input = tool_use.input
            if isinstance(tool_input, dict):
                pass
            elif tool_use.id in current_tool_input_buffers:
                try:
                    tool_input = json.loads(current_tool_input_buffers[tool_use.id])
                except json.JSONDecodeError:
                    tool_input = {}

            if settings.chat_trace:
                preview = json.dumps(tool_input, ensure_ascii=False)
                if len(preview) > 800:
                    preview = preview[:800] + "..."
                logger.info(
                    "chat executing tool name=%s input=%s",
                    tool_use.name,
                    preview,
                )

            result = await _execute_tool(
                tool_name=tool_use.name,
                tool_input=tool_input,
                team_id=team_id,
                user_id=user_id,
                db=db,
            )

            if settings.chat_trace:
                rpreview = result if len(result) <= 600 else result[:600] + "..."
                logger.info(
                    "chat tool done name=%s result_preview=%s",
                    tool_use.name,
                    rpreview,
                )

            yield _format_sse(
                {
                    "type": "tool_result",
                    "tool_name": tool_use.name,
                    "content": result,
                    "tool_use_id": tool_use.id,
                }
            )
            for extra in _extra_events_after_tool(tool_use.name, result):
                yield _format_sse(extra)

            # Add tool result as a user message content block
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": result,
                        }
                    ],
                }
            )

    # Build final text content if we exited the loop after tool iterations
    if final_text_content is None and all_assistant_content:
        # Concatenate all text from all assistant content blocks
        texts = []
        for blocks in all_assistant_content:
            for block in blocks:
                if hasattr(block, "type") and block.type == "text":
                    texts.append(block.text)
                elif isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
        final_text_content = "".join(texts)

    # Save the assistant's final response to DB
    if final_text_content:
        await _save_message(db, team_id, user_id, "assistant", final_text_content)
    elif collected_tool_uses := [
        b for blocks in all_assistant_content
        for b in (blocks if isinstance(blocks, list) else [blocks])
        if hasattr(b, "type") and b.type == "tool_use"
    ]:
        # If only tool calls were made, save a summary
        tool_names = ", ".join(t.name for t in collected_tool_uses)
        await _save_message(db, team_id, user_id, "assistant", f"[调用了工具: {tool_names}]")

    # Signal end of stream
    yield _format_sse({"type": "message_stop"})
