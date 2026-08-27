from pathlib import Path

from ileapp_mcp.server import (
    case_manager,
    get_call_history,
    get_case_info,
    get_device_info,
    get_installed_apps,
    get_location_history,
    get_messages,
    get_timeline,
    get_web_activity,
    list_available_artifacts,
    load_case,
    mcp,
    run_readonly_sql,
)


def test_mcp_server_tools_registered() -> None:
    # Ensure FastMCP has registered all expected tools
    assert mcp.name == "iLEAPP Forensic Server"


def test_server_workflow_e2e(mock_case_dir: Path) -> None:
    # 1. Load case
    case_info = load_case(str(mock_case_dir))
    assert case_info.loaded
    assert case_info.total_artifacts >= 5

    # 2. Get case info
    info = get_case_info()
    assert info.loaded

    # 3. Device info
    dev_info = get_device_info()
    assert dev_info.device_name == "iPhone 14 Pro de John Doe"

    # 4. Messages
    msgs = get_messages(keyword="Eiffel")
    assert msgs.total_count == 1

    # 5. Calls
    calls = get_call_history()
    assert calls.total_count >= 3

    # 6. Locations
    locations = get_location_history()
    assert locations.total_count >= 3

    # 7. Web
    web = get_web_activity()
    assert web.total_count >= 3

    # 8. Apps
    apps = get_installed_apps()
    assert apps.total_count >= 3

    # 9. Timeline
    timeline = get_timeline()
    assert timeline.total_count >= 10

    # 10. List artifacts
    artifacts = list_available_artifacts()
    assert len(artifacts) >= 5

    # 11. Readonly SQL
    sql_res = run_readonly_sql("SELECT COUNT(*) as cnt FROM messages", db_name="sms")
    assert sql_res.row_count == 1
    assert sql_res.rows[0]["cnt"] == 4

    case_manager.close()
