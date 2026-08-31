from ileapp_mcp.modules.networks import get_network_connections


def test_get_networks(loaded_case):
    res = get_network_connections(loaded_case)
    assert res.total_count == 2
    assert len(res.items) == 2
    assert res.items[0].ssid_or_name == "Home_WiFi"


def test_get_networks_filter(loaded_case):
    res = get_network_connections(loaded_case, ssid_or_name="Starbucks")
    assert res.total_count == 1
    assert res.items[0].bssid_or_mac == "66:77:88:99:AA:BB"
