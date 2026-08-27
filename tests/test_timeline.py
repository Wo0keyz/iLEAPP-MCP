from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.timeline import get_timeline


def test_get_timeline_all(loaded_case: CaseManager) -> None:
    res = get_timeline(loaded_case)
    assert res.total_count >= 10

    # Ensure strictly sorted by timestamp ascending
    timestamps = [e.timestamp for e in res.items]
    assert timestamps == sorted(timestamps)


def test_get_timeline_filtered_categories(loaded_case: CaseManager) -> None:
    res = get_timeline(loaded_case, categories=["messages", "calls"])
    assert res.total_count >= 6
    categories = {e.category for e in res.items}
    assert categories.issubset({"messages", "calls"})
