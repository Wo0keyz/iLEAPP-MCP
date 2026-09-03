from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.networks import get_network_connections


def test_get_networks(loaded_case: CaseManager) -> None:
    res = get_network_connections(loaded_case)
    assert res.total_count == 2
    assert len(res.items) == 2
    names = [x.ssid_or_name for x in res.items]
    assert "Home_WiFi" in names


def test_get_networks_filter(loaded_case: CaseManager) -> None:
    res = get_network_connections(loaded_case, ssid_or_name="Starbucks")
    assert res.total_count == 1
    assert res.items[0].bssid_or_mac == "66:77:88:99:AA:BB"
