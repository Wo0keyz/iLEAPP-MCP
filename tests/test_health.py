from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.health import get_health_data


def test_get_health_data(loaded_case: CaseManager) -> None:
    res = get_health_data(loaded_case)
    assert res.total_count == 2
    assert len(res.items) == 2
    values = [x.value for x in res.items]
    assert "1250" in values
    assert "450" in values


def test_get_health_data_filter(loaded_case: CaseManager) -> None:
    res = get_health_data(loaded_case, metric_type="steps", limit=1)
    assert len(res.items) == 1
    assert res.items[0].metric_type.lower() == "steps"
