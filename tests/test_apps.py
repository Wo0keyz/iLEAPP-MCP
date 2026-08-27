from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.apps import get_installed_apps


def test_get_installed_apps_all(loaded_case: CaseManager) -> None:
    res = get_installed_apps(loaded_case)
    assert res.total_count == 3
    names = [a.app_name for a in res.items]
    assert "Signal" in names
    assert "WhatsApp" in names
    assert "Proton Mail" in names


def test_get_installed_apps_bundle_id(loaded_case: CaseManager) -> None:
    res = get_installed_apps(loaded_case, bundle_id="org.whispersystems.signal")
    assert res.total_count == 1
    app = res.items[0]
    assert app.app_name == "Signal"
    assert "Camera" in app.permissions
    assert "Microphone" in app.permissions


def test_get_installed_apps_filter_name(loaded_case: CaseManager) -> None:
    res = get_installed_apps(loaded_case, app_name="Proton")
    assert res.total_count == 1
    assert res.items[0].developer == "Proton AG"
