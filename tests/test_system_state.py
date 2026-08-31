from ileapp_mcp.modules.system_state import get_system_state


def test_get_system_state(loaded_case):
    res = get_system_state(loaded_case)
    assert res.total_count == 3
    assert len(res.items) == 3
    assert res.items[0].value == "100"


def test_get_system_state_filter(loaded_case):
    res = get_system_state(loaded_case, start_date="2025-10-14 12:00:00")
    assert res.total_count == 2
