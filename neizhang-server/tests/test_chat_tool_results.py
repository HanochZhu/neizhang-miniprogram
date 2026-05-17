"""工具结果消息格式：须合并为单条 user 消息。"""


def test_tool_results_must_be_single_user_message():
    """模拟修复后的结构：1 条 assistant + 1 条 user(多 tool_result)。"""
    messages = [
        {"role": "user", "content": "全部重新记录"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "call_01", "name": "add_transaction"},
                {"type": "tool_use", "id": "call_02", "name": "add_transaction"},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_01", "content": "{}"},
                {"type": "tool_result", "tool_use_id": "call_02", "content": "{}"},
            ],
        },
    ]
    assistant_idx = next(
        i for i, m in enumerate(messages) if m["role"] == "assistant"
    )
    next_msg = messages[assistant_idx + 1]
    assert next_msg["role"] == "user"
    assert isinstance(next_msg["content"], list)
    assert len(next_msg["content"]) == 2
    assert all(b["type"] == "tool_result" for b in next_msg["content"])
