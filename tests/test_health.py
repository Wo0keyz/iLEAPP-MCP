from ileapp_mcp.modules.health import get_health_data


def test_get_health_data(loaded_case):
    res = get_health_data(loaded_case)
    assert res.total_count == 2
    assert len(res.items) == 2
    assert res.items[0].value == "1250"
    assert res.items[1].value == "450"


def test_get_health_data_filter(loaded_case):
    res = get_health_data(loaded_case, metric_type="steps", limit=1)
    assert len(res.items) == 1
    assert res.items[0].metric_type.lower() == "steps"
