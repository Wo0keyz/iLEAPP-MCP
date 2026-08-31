from ileapp_mcp.modules.notes import get_notes_and_memos


def test_get_notes(loaded_case):
    res = get_notes_and_memos(loaded_case)
    assert res.total_count >= 2
    assert len(res.items) >= 2
    titles = [x.title for x in res.items]
    assert "Grocery List" in titles


def test_get_notes_filter(loaded_case):
    res = get_notes_and_memos(loaded_case, keyword="roadmap")
    assert res.total_count == 1
    assert res.items[0].title == "Meeting Notes"
