from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.locations import get_location_history, haversine_distance_km


def test_haversine_distance_calculation() -> None:
    # Paris Tour Eiffel (48.8584, 2.2945) to Louvre (48.8606, 2.3376) is ~3.2 km
    dist = haversine_distance_km(48.8584, 2.2945, 48.8606, 2.3376)
    assert 3.0 < dist < 3.5

    # Paris to Lyon is ~390 km
    dist_lyon = haversine_distance_km(48.8584, 2.2945, 45.7640, 4.8357)
    assert 380.0 < dist_lyon < 410.0


def test_get_location_history_all(loaded_case: CaseManager) -> None:
    res = get_location_history(loaded_case)
    assert res.total_count >= 3
    sources = {loc.source_type for loc in res.items}
    assert (
        "Significant Locations" in sources or "Location TSV" in sources or "Apple Maps" in sources
    )


def test_get_location_history_haversine_radius(loaded_case: CaseManager) -> None:
    # Query centered around Tour Eiffel (48.8584, 2.2945) with radius 5km
    # Should include Tour Eiffel (0km) and Louvre (~3.2km), but NOT Lyon (~390km)
    paris_res = get_location_history(
        loaded_case,
        latitude=48.8584,
        longitude=2.2945,
        radius_km=5.0,
    )
    assert paris_res.total_count >= 2
    for loc in paris_res.items:
        assert loc.latitude is not None and loc.longitude is not None
        dist = haversine_distance_km(48.8584, 2.2945, loc.latitude, loc.longitude)
        assert dist <= 5.0
