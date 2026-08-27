from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.web import get_web_activity


def test_get_web_activity_all(loaded_case: CaseManager) -> None:
    res = get_web_activity(loaded_case)
    assert res.total_count >= 3
    urls = [w.url for w in res.items]
    assert any("github.com/abrignoni/iLEAPP" in (u or "") for u in urls)


def test_get_web_activity_search_term(loaded_case: CaseManager) -> None:
    res = get_web_activity(loaded_case, search_query="forensic")
    assert res.total_count >= 1
    item = res.items[0]
    assert item.search_term == "forensic investigation tools"
    assert item.record_type == "search"


def test_get_web_activity_domain_filter(loaded_case: CaseManager) -> None:
    res = get_web_activity(loaded_case, domain="apple.com")
    assert res.total_count == 1
    assert "apple.com" in (res.items[0].url or "")
