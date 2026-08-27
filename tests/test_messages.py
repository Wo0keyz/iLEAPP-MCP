from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.messages import get_messages


def test_get_all_messages(loaded_case: CaseManager) -> None:
    res = get_messages(loaded_case, limit=50)
    assert res.total_count >= 5  # 4 SMS/iMessage + 2 WhatsApp
    assert len(res.items) == res.total_count
    assert not res.has_more


def test_get_messages_filtered_by_app(loaded_case: CaseManager) -> None:
    wa_res = get_messages(loaded_case, app="WhatsApp")
    assert wa_res.total_count == 2
    assert all(m.app == "WhatsApp" for m in wa_res.items)


def test_get_messages_keyword_search(loaded_case: CaseManager) -> None:
    res = get_messages(loaded_case, keyword="Eiffel")
    assert res.total_count == 1
    assert "Eiffel" in (res.items[0].message_text or "")


def test_get_messages_sender_filter(loaded_case: CaseManager) -> None:
    res = get_messages(loaded_case, sender="+33698765432")
    assert res.total_count >= 1
    assert res.items[0].sender == "+33698765432"


def test_get_messages_date_range(loaded_case: CaseManager) -> None:
    res = get_messages(
        loaded_case,
        start_date="2026-08-21 00:00:00",
        end_date="2026-08-22 23:59:59",
    )
    assert res.total_count == 2


def test_get_messages_pagination(loaded_case: CaseManager) -> None:
    page1 = get_messages(loaded_case, limit=2, offset=0)
    assert len(page1.items) == 2
    assert page1.has_more
    assert page1.next_offset == 2

    page2 = get_messages(loaded_case, limit=2, offset=page1.next_offset or 0)
    assert len(page2.items) == 2
    assert page2.items[0] != page1.items[0]
