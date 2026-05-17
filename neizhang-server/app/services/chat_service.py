import json
import logging
from datetime import datetime
from typing import Any, AsyncGenerator, Optional

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.chat_message import ChatMessage
from app.services.chat_tool_guard import check_add_transaction_allowed, make_tool_guard
from app.services.context_service import (
    append_user_message,
    get_recent_messages,
    is_duplicate_of_last_message,
)
from sqlalchemy import select

from app.models.transaction_proposal import TransactionProposal
from app.tools.finance_tools import (
    add_transaction,
    get_summary,
    propose_transaction,
    query_transactions,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是内账助手，一个专注于财务记账和费用管理的AI助手。"
    "你只能回答与财务、记账、费用管理相关的问题。"
    "如果用户询问与财务无关的问题，请礼貌地告知你只能帮助处理财务相关的事务，并引导用户回到记账话题。\n\n"
    "你可以使用以下工具来帮助用户管理财务：\n"
    "- add_transaction: 在信息明确时直接添加一笔收支记录\n"
    "- propose_transaction: 当你推测出记账内容但不确定是否应保存时，发起待确认提案（不会立即入账）\n"
    "- query_transactions: 查询收支记录（支持 category 精确筛选 + keyword 模糊搜索）\n"
    "- get_summary: 获取财务汇总\n\n"
    "请始终使用中文回复。\n\n"
    "重要规则：\n"
    "【第一步：判断用户意图 —— 查询还是记账？】\n"
    "先判断用户是想「查」还是想「记」：\n"
    "- 查询意图（用 query_transactions / get_summary）：用户问「花了多少」「收入多少」「看看开支」「查询」「汇总」「还剩多少」「有没有记过」「统计」等 —— 只查询不记账。\n"
    "- 记账意图（用 add_transaction / propose_transaction）：用户明确说「记一笔」「帮我记」「我花了XX」「收到了XX」等 —— 执行记账操作。\n"
    "如果用户只说「吃饭花了多少钱」但没有说具体金额，这是在查询历史记录，不是记账！\n\n"
    "【查询规则 —— 如何处理模糊查询】\n"
    "用户经常使用模糊表达来查询，你需要正确选择参数：\n"
    "1. 模糊类别 → 用 keyword 参数：用户说「酒水」「吃饭」「早餐」「打车」「咖啡」等非标准类别名时，使用 keyword 参数（会匹配 category 和 description 字段）。不要用 category（category 是精确匹配）。\n"
    "2. 精确类别 → 用 category 参数：仅当用户说出系统中已有的标准类别名（如「餐饮」「交通」「工资」）时使用。\n"
    "3. 时间表达转换：\n"
    "   - 「今天」→ start_date=今天日期\n"
    "   - 「昨天」→ start_date=昨天日期, end_date=今天日期\n"
    "   - 「本周」→ start_date=本周一, end_date=下周一\n"
    "   - 「这个月」→ start_date=本月1日, end_date=下月1日\n"
    "   - 「早上」「上午」「下午」→ 设定对应日期范围即可（数据库不存储具体时间）\n"
    "4. 如果 query_transactions 返回「没有找到匹配的收支记录」，告诉用户目前没有相关记录，并建议用户调整搜索词。\n\n"
    "【记账规则】\n"
    "1. **仅根据「当前这一条用户消息」中明确写出的收支来记账**；"
    "更早的聊天历史、助手过往回复、工具返回摘要仅供理解语境，**不得**从中挖掘多笔金额并批量调用 add_transaction。\n"
    "2. 用户表述清晰、金额/类别/收支类型均在**当前消息**中无歧义时，使用 add_transaction；"
    "同一句里有多笔明确金额时，最多按句中笔数分别入账。\n"
    "3. 用户说「全部重新记录」「把上面的都记了」「补记之前说的」等时：**禁止**根据历史对话批量入账；"
    "应先 query_transactions 说明库里已有记录，并引导用户在本条消息逐条列出要记的账，或一次记一笔。\n"
    "4. 只有以下情况才使用 propose_transaction：金额或类别需推测、日期不明确、用户犹豫或说「大概」「好像」等。\n"
    "5. propose_transaction 的 reason 用一句话说明需确认原因；正文须提示「尚未入账，请在确认卡片中确认保存」。\n"
    "6. 关键信息缺失时先追问，不要猜测后入账或口头声称已记账。\n"
    "7. 禁止在未成功调用 add_transaction 之前写「已记账」「已保存」「已记录」。\n"
    "8. add_transaction 返回 success 后，再用一句话确认（含金额与类别）。"
)

WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]


def _build_date_hint() -> str:
    """告诉模型当前日期，让它能正确转换「今天」「本周」等时间表达。"""
    now = datetime.now()
    return f"\n\n当前日期：{now.strftime('%Y-%m-%d')}（周{WEEKDAY_NAMES[now.weekday()]}）。"

TOOLS = [
    {
        "name": "propose_transaction",
        "description": "发起一笔待用户确认的收支提案（不立即保存）。当记账信息需推测或你不确定是否应入账时使用。",
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
                "reason": {
                    "type": "string",
                    "description": "需要用户确认的原因（一句话）",
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
            "required": ["type", "amount", "category", "reason"],
        },
    },
    {
        "name": "add_transaction",
        "description": (
            "在信息明确时直接添加一笔收支记录。"
            "仅针对用户「当前这条消息」里明确说出的那一笔；"
            "不得根据更早聊天记录批量补记多笔。"
        ),
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
        "description": "查询收支记录。用户模糊查询时优先使用 keyword 参数（如「酒水」「早上」等非精确类别的词）",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "开始日期 YYYY-MM-DD。相对时间如「今天」「昨天」「本周」需先换算为具体日期。",
                },
                "end_date": {
                    "type": "string",
                    "description": "结束日期 YYYY-MM-DD",
                },
                "category": {
                    "type": "string",
                    "description": "按类别精确筛选。仅当用户明确说出已有类别名（如「餐饮」「交通」）时使用。",
                },
                "product": {
                    "type": "string",
                    "description": "按产品/项目筛选",
                },
                "type": {
                    "type": "string",
                    "enum": ["income", "expense"],
                    "description": "类型：income=收入, expense=支出",
                },
                "keyword": {
                    "type": "string",
                    "description": "模糊搜索关键词，同时匹配类别和描述字段。用户说「酒水」「吃饭」「早餐」等模糊词时优先用此参数，不要用 category。",
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


def _parse_tool_result(result: str) -> dict:
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return {}


def _confirmation_sse_from_propose(result: str) -> Optional[dict]:
    data = _parse_tool_result(result)
    if not data.get("success") or not data.get("pending"):
        return None
    tx = data.get("transaction") or {}
    return {
        "type": "confirmation_required",
        "proposal_id": data.get("proposal_id"),
        "message": data.get("message", "请确认是否保存该笔记录"),
        "reason": data.get("reason"),
        "transaction": tx,
    }


def _extra_events_after_tool(tool_name: str, result: str) -> list[dict]:
    """SSE events to push after a tool finishes (e.g. confirm记账成功)."""
    events: list[dict] = []
    if tool_name == "propose_transaction":
        confirm_event = _confirmation_sse_from_propose(result)
        if confirm_event:
            events.append(confirm_event)
            events.append(
                {
                    "type": "text_delta",
                    "content": confirm_event.get("message", ""),
                }
            )
        return events
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


async def _commit_if_success(db: AsyncSession, result: str) -> None:
    """Persist write-tool results immediately (stream may end later)."""
    data = _parse_tool_result(result)
    if data.get("success"):
        await db.commit()


async def _execute_tool(
    tool_name: str,
    tool_input: dict,
    team_id: int,
    user_id: int,
    db: AsyncSession,
    tool_guard: Optional[dict[str, Any]] = None,
) -> str:
    """Execute a finance tool and return the result string."""
    if tool_name == "add_transaction" and tool_guard is not None:
        blocked = check_add_transaction_allowed(
            tool_guard.get("user_message", ""),
            tool_guard.get("add_count", 0),
        )
        if blocked:
            return blocked
        tool_guard["add_count"] = tool_guard.get("add_count", 0) + 1

    if tool_name == "propose_transaction":
        result = await propose_transaction(
            team_id=team_id,
            user_id=user_id,
            tx_type=tool_input.get("type", ""),
            amount=tool_input.get("amount", 0),
            category=tool_input.get("category", ""),
            reason=tool_input.get("reason", "需要您确认是否保存"),
            description=tool_input.get("description"),
            product=tool_input.get("product"),
            transaction_date=tool_input.get("transaction_date"),
            db=db,
        )
        await _commit_if_success(db, result)
        return result
    elif tool_name == "add_transaction":
        result = await add_transaction(
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
        await _commit_if_success(db, result)
        return result
    elif tool_name == "query_transactions":
        return await query_transactions(
            team_id=team_id,
            user_id=user_id,
            start_date=tool_input.get("start_date"),
            end_date=tool_input.get("end_date"),
            category=tool_input.get("category"),
            product=tool_input.get("product"),
            tx_type=tool_input.get("type"),
            keyword=tool_input.get("keyword"),
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
    *,
    force: bool = False,
) -> None:
    """持久化消息；与库中最新一条相同且未 force 时跳过（由上层先征求用户确认）。"""
    text = content.strip() if isinstance(content, str) else str(content)
    if not force and await is_duplicate_of_last_message(team_id, role, text, db):
        return

    msg = ChatMessage(
        team_id=team_id,
        user_id=user_id,
        role=role,
        content=text,
    )
    db.add(msg)
    await db.flush()


async def chat_stream(
    team_id: int,
    user_id: int,
    user_message: str,
    db: AsyncSession,
    *,
    force_save_user: bool = False,
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

    text = user_message.strip()

    if not force_save_user and await is_duplicate_of_last_message(
        team_id, "user", text, db
    ):
        yield _format_sse(
            {
                "type": "duplicate_message_required",
                "role": "user",
                "content": text,
                "message": "该消息与上一条聊天记录相同，是否仍要保存并继续对话？",
            }
        )
        yield _format_sse({"type": "message_stop"})
        return

    # 历史只读（可由 CHAT_LOAD_HISTORY 关闭）：仅拼 LLM 上下文，不对 history 逐条写库
    history = await get_recent_messages(team_id, db, limit=20)
    messages = append_user_message(history, text)

    await _save_message(
        db, team_id, user_id, "user", text, force=force_save_user
    )

    tool_guard = make_tool_guard(text)

    # Buffer for the full assistant response content blocks across turns
    all_assistant_content: list = []
    last_tool_results: list = []
    final_text_content: Optional[str] = None

    awaiting_user_confirmation = False

    # ReAct loop (max 5 iterations to prevent infinite loops)
    for iteration in range(5):
        if awaiting_user_confirmation:
            break
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
            system=SYSTEM_PROMPT + _build_date_hint(),
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

        # API 要求：下一条 user 消息须包含本轮全部 tool_result（不能拆成多条 user）
        tool_result_blocks: list[dict] = []
        stop_tool_round = False

        for tool_use in tool_use_blocks:
            if stop_tool_round:
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": json.dumps(
                            {"error": "本轮已暂停，未执行该工具调用"},
                            ensure_ascii=False,
                        ),
                    }
                )
                continue

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
                tool_guard=tool_guard,
            )

            if settings.chat_trace:
                rpreview = result if len(result) <= 600 else result[:600] + "..."
                logger.info(
                    "chat tool done name=%s result_preview=%s",
                    tool_use.name,
                    rpreview,
                )

            tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                }
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

            if tool_use.name == "propose_transaction":
                parsed = _parse_tool_result(result)
                if parsed.get("pending"):
                    awaiting_user_confirmation = True
                    if parsed.get("message"):
                        final_text_content = parsed["message"]
                    stop_tool_round = True

        if tool_result_blocks:
            messages.append({"role": "user", "content": tool_result_blocks})

        if awaiting_user_confirmation:
            break

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


async def confirm_duplicate_message_stream(
    user_message: str,
    confirmed: bool,
    team_id: int,
    user_id: int,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """用户确认或取消重复消息保存后，继续或结束对话。"""
    text = user_message.strip()
    if not text:
        yield _format_sse({"type": "error", "content": "消息不能为空"})
        yield _format_sse({"type": "message_stop"})
        return

    if not confirmed:
        yield _format_sse(
            {
                "type": "duplicate_message_cancelled",
                "content": "已取消，未重复保存该消息。",
            }
        )
        yield _format_sse({"type": "message_stop"})
        return

    yield _format_sse({"type": "duplicate_message_confirmed"})
    async for chunk in chat_stream(
        team_id=team_id,
        user_id=user_id,
        user_message=text,
        db=db,
        force_save_user=True,
    ):
        yield chunk


async def confirm_proposal_stream(
    proposal_id: str,
    confirmed: bool,
    team_id: int,
    user_id: int,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """用户确认或取消待记账提案后，执行保存或取消并流式返回结果。"""
    result = await db.execute(
        select(TransactionProposal).where(
            TransactionProposal.id == proposal_id,
            TransactionProposal.team_id == team_id,
            TransactionProposal.user_id == user_id,
        )
    )
    proposal = result.scalar_one_or_none()

    if proposal is None:
        yield _format_sse({"type": "error", "content": "未找到该待确认记录或无权操作"})
        yield _format_sse({"type": "message_stop"})
        return

    if proposal.status != "pending":
        yield _format_sse(
            {
                "type": "error",
                "content": "该提案已处理，请勿重复操作",
            }
        )
        yield _format_sse({"type": "message_stop"})
        return

    if confirmed:
        tool_result = await add_transaction(
            team_id=team_id,
            user_id=user_id,
            tx_type=proposal.type,
            amount=proposal.amount,
            category=proposal.category,
            description=proposal.description,
            product=proposal.product,
            transaction_date=proposal.transaction_date,
            db=db,
        )
        proposal.status = "confirmed"
        data = _parse_tool_result(tool_result)
        if data.get("success"):
            message = data.get("message", "已保存")
            yield _format_sse({"type": "proposal_confirmed", "proposal_id": proposal_id})
            for extra in _extra_events_after_tool("add_transaction", tool_result):
                yield _format_sse(extra)
            await _save_message(db, team_id, user_id, "assistant", message)
        else:
            message = data.get("error", "保存失败")
            proposal.status = "pending"
            yield _format_sse({"type": "error", "content": message})
    else:
        proposal.status = "cancelled"
        message = "已取消，未保存该笔记录。"
        yield _format_sse(
            {
                "type": "proposal_cancelled",
                "proposal_id": proposal_id,
                "content": message,
            }
        )
        yield _format_sse({"type": "text_delta", "content": message})
        await _save_message(db, team_id, user_id, "assistant", message)

    await db.flush()
    yield _format_sse({"type": "message_stop"})
