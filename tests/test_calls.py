from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.calls import get_call_history


def test_get_call_history_all(loaded_case: CaseManager) -> None:
    res = get_call_history(loaded_case)
    assert res.total_count == 3
    assert len(res.items) == 3


def test_get_call_history_filter_contact(loaded_case: CaseManager) -> None:
    res = get_call_history(loaded_case, phone_number="Alice")
    assert res.total_count == 2
    assert all("Alice" in (c.contact_name or "") for c in res.items)


def test_get_call_history_filter_type(loaded_case: CaseManager) -> None:
    missed_res = get_call_history(loaded_case, call_type="Missed")
    assert missed_res.total_count == 1
    assert missed_res.items[0].call_type == "Missed"
    assert missed_res.items[0].duration_seconds == 0


def test_get_call_history_duration_parsing(loaded_case: CaseManager) -> None:
    res = get_call_history(loaded_case, phone_number="Alice")
    durations = [c.duration_seconds for c in res.items]
    assert 125 in durations  # 125 seconds
    assert 330 in durations  # 05:30 -> 330 seconds
