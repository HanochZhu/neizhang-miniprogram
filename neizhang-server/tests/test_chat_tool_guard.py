"""记账工具调用防护。"""

import json

from app.services.chat_tool_guard import (
    check_add_transaction_allowed,
    count_explicit_booking_items_in_message,
    is_bulk_rerecord_intent,
    max_add_transactions_allowed,
)


def test_bulk_rerecord_intent():
    assert is_bulk_rerecord_intent("全部重新记录")
    assert is_bulk_rerecord_intent("把上面说的重新记一下")
    assert not is_bulk_rerecord_intent("午餐花了50元")


def test_explicit_booking_count():
    assert count_explicit_booking_items_in_message("午餐50元，打车30块") == 2
    assert count_explicit_booking_items_in_message("记一笔") == 0


def test_max_add_allowed():
    assert max_add_transactions_allowed("全部重新记录") == 0
    assert max_add_transactions_allowed("午餐50元，咖啡20元") == 2
    assert max_add_transactions_allowed("记一笔") == 1


def test_blocks_bulk_add():
    err = check_add_transaction_allowed("全部重新记录", 0)
    assert err is not None
    data = json.loads(err)
    assert data["blocked"] is True


def test_blocks_second_add_without_two_amounts():
    err = check_add_transaction_allowed("午餐50元", 1)
    assert err is not None
