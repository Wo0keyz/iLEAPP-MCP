import logging
import os
from typing import Any

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[attr-defined,no-redef]
    except ImportError:
        from fastmcp import FastMCP  # type: ignore[import-not-found,no-redef]

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import (
    AppRecord,
    ArtifactInfo,
    CallRecord,
    CaseInfo,
    DeviceInfo,
    HealthRecord,
    LocationRecord,
    MessageRecord,
    NetworkRecord,
    NoteRecord,
    PaginatedResult,
    PhotoRecord,
    SqlQueryResult,
    SystemStateRecord,
    TimelineEvent,
    WebRecord,
)
from ileapp_mcp.modules.apps import get_installed_apps as _get_installed_apps
from ileapp_mcp.modules.calls import get_call_history as _get_call_history
from ileapp_mcp.modules.device_info import get_device_info as _get_device_info
from ileapp_mcp.modules.generic import (
    get_raw_artifact_data as _get_raw_artifact_data,
)
from ileapp_mcp.modules.generic import (
    list_available_artifacts as _list_available_artifacts,
)
from ileapp_mcp.modules.generic import (
    run_readonly_sql as _run_readonly_sql,
)
from ileapp_mcp.modules.health import get_health_data as _get_health_data
from ileapp_mcp.modules.locations import get_location_history as _get_location_history
from ileapp_mcp.modules.messages import get_messages as _get_messages
from ileapp_mcp.modules.networks import get_network_connections as _get_network_connections
from ileapp_mcp.modules.notes import get_notes_and_memos as _get_notes_and_memos
from ileapp_mcp.modules.photos import get_photos_metadata as _get_photos_metadata
from ileapp_mcp.modules.system_state import get_system_state as _get_system_state
from ileapp_mcp.modules.timeline import get_timeline as _get_timeline
from ileapp_mcp.modules.web import get_web_activity as _get_web_activity

logger = logging.getLogger(__name__)

# Create the FastMCP Server instance
mcp = FastMCP("iLEAPP Forensic Server")

# Global case manager instance
case_manager = CaseManager()

# Auto-load case if environment variable is set
default_case_env = os.environ.get("ILEAPP_REPORT_DIR")
if default_case_env:
    try:
        case_manager.load_case(default_case_env)
        logger.info("Auto-loaded initial iLEAPP case from ILEAPP_REPORT_DIR: %s", default_case_env)
    except Exception as e:
        logger.warning("Failed to auto-load ILEAPP_REPORT_DIR '%s': %s", default_case_env, e)


@mcp.tool()
def load_case(path: str) -> CaseInfo:
    """Load or switch dynamically to an iLEAPP extraction output directory.

    Args:
        path: Absolute or relative path to the iLEAPP report output folder.
    """
    case_manager.load_case(path)
    return get_case_info()


@mcp.tool()
def get_case_info() -> CaseInfo:
    """Get the current case status, index overview, and summary of discovered artifacts."""
    if not case_manager.is_loaded or not case_manager.case_path:
        return CaseInfo(
            case_path="None",
            loaded=False,
            total_artifacts=0,
            sqlite_databases=[],
            tsv_files=[],
            device_summary={},
        )

    all_dbs = [p.name for p in case_manager.get_all_sqlite_dbs()]
    all_tsvs = [p.name for p in case_manager.get_all_tsv_files()]

    dev_summary = {}
    try:
        info = _get_device_info(case_manager)
        if info.device_name:
            dev_summary["Device Name"] = info.device_name
        if info.ios_version:
            dev_summary["iOS Version"] = info.ios_version
        if info.product_type:
            dev_summary["Model"] = info.product_type
        if info.serial_number:
            dev_summary["Serial"] = info.serial_number
    except Exception:
        pass

    return CaseInfo(
        case_path=str(case_manager.case_path),
        loaded=True,
        total_artifacts=len(all_dbs) + len(all_tsvs),
        sqlite_databases=all_dbs,
        tsv_files=all_tsvs,
        device_summary=dev_summary,
    )


@mcp.tool()
def get_device_info() -> DeviceInfo:
    """Extract hardware serial, model, iOS firmware, timezone, and acquisition metadata."""
    return _get_device_info(case_manager)


@mcp.tool()
def get_messages(
    sender: str | None = None,
    recipient: str | None = None,
    keyword: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    app: str = "all",
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[MessageRecord]:
    """Retrieve and filter chat messages across SMS, iMessage, WhatsApp, Telegram, and Signal.

    Args:
        sender: Filter by sender name, phone number, or ID.
        recipient: Filter by recipient name, phone number, or ID.
        keyword: Search keyword in message body or contact fields.
        start_date: Start date/timestamp filter (ISO format or YYYY-MM-DD).
        end_date: End date/timestamp filter (ISO format or YYYY-MM-DD).
        app: App filter ('all', 'iMessage', 'SMS', 'WhatsApp', 'Telegram', etc.).
        limit: Number of records to return per page (max 250, default 50).
        offset: Offset for pagination.
    """
    return _get_messages(
        case_manager,
        sender=sender,
        recipient=recipient,
        keyword=keyword,
        start_date=start_date,
        end_date=end_date,
        app=app,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def get_call_history(
    phone_number: str | None = None,
    call_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[CallRecord]:
    """Retrieve and filter call logs (Cellular, FaceTime, WhatsApp) with duration and timestamps.

    Args:
        phone_number: Filter by phone number or contact identifier.
        call_type: Filter by call direction/type ('Incoming', 'Outgoing', 'Missed', 'Rejected').
        start_date: Start timestamp (ISO format or YYYY-MM-DD).
        end_date: End timestamp (ISO format or YYYY-MM-DD).
        limit: Page size limit (max 250, default 50).
        offset: Pagination offset.
    """
    return _get_call_history(
        case_manager,
        phone_number=phone_number,
        call_type=call_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def get_location_history(
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    source_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[LocationRecord]:
    """Retrieve geo-coordinates, significant locations, Apple Maps visits, and routine caches.

    Args:
        latitude: Target latitude for geographic radius search.
        longitude: Target longitude for geographic radius search.
        radius_km: Radius in kilometers around the target coordinates.
        source_type: Filter by source ('Significant Locations', 'Apple Maps', 'LocationD', etc.).
        start_date: Start timestamp (ISO format or YYYY-MM-DD).
        end_date: End timestamp (ISO format or YYYY-MM-DD).
        limit: Page size limit (max 250, default 50).
        offset: Pagination offset.
    """
    return _get_location_history(
        case_manager,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        source_type=source_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def get_web_activity(
    domain: str | None = None,
    search_query: str | None = None,
    activity_type: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[WebRecord]:
    """Retrieve and filter Safari/Chrome web browsing history, search engine queries, and downloads.

    Args:
        domain: Filter by website domain or title keyword.
        search_query: Filter by search term extracted from query URLs or search history.
        activity_type: Filter by record type ('all', 'history', 'search', 'download', 'bookmark').
        start_date: Start timestamp (ISO format or YYYY-MM-DD).
        end_date: End timestamp (ISO format or YYYY-MM-DD).
        limit: Page size limit (max 250, default 50).
        offset: Pagination offset.
    """
    return _get_web_activity(
        case_manager,
        domain=domain,
        search_query=search_query,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def get_installed_apps(
    app_name: str | None = None,
    bundle_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[AppRecord]:
    """Inspect installed iOS applications, bundle identifiers, install timestamps, and permissions.

    Args:
        app_name: Filter by application display name.
        bundle_id: Filter by bundle ID (e.g. 'com.apple.mobilesafari').
        limit: Page size limit (max 250, default 50).
        offset: Pagination offset.
    """
    return _get_installed_apps(
        case_manager,
        app_name=app_name,
        bundle_id=bundle_id,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def get_timeline(
    start_date: str | None = None,
    end_date: str | None = None,
    categories: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> PaginatedResult[TimelineEvent]:
    """Generate a unified chronological event timeline across communications, web, locations, and apps.

    Args:
        start_date: Start timestamp (ISO format or YYYY-MM-DD).
        end_date: End timestamp (ISO format or YYYY-MM-DD).
        categories: List of categories to include (e.g. ['messages', 'calls', 'web', 'locations', 'apps']).
        limit: Page size limit (max 500, default 100).
        offset: Pagination offset.
    """
    return _get_timeline(
        case_manager,
        start_date=start_date,
        end_date=end_date,
        categories=categories,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def list_available_artifacts() -> list[ArtifactInfo]:
    """List all available forensic artifacts (SQLite tables and TSV files) in the loaded iLEAPP report."""
    return _list_available_artifacts(case_manager)


@mcp.tool()
def get_raw_artifact_data(
    artifact_name: str,
    filters: dict[str, str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[dict[str, Any]]:
    """Query raw tabular data from any specific artifact (e.g. 'Apple_Notes', 'SMS_&_iMessage.db:messages').

    Args:
        artifact_name: Name of the TSV file or SQLite table (format 'artifact_name' or 'db_name:table_name').
        filters: Key-value filters to match against record fields.
        limit: Page size limit (max 250, default 50).
        offset: Pagination offset.
    """
    return _get_raw_artifact_data(
        case_manager,
        artifact_name=artifact_name,
        filters=filters,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def run_readonly_sql(
    query: str,
    db_name: str | None = None,
    max_rows: int = 100,
) -> SqlQueryResult:
    """Execute a safe, strictly read-only SQL query (SELECT) against a discovered SQLite database.

    Args:
        query: SQL SELECT query to execute. Mutations (DROP, INSERT, UPDATE, etc.) are strictly rejected.
        db_name: Name or partial name of the database file to target (e.g. 'sms', 'safari'). If None, uses default.
        max_rows: Maximum rows to return (max 500, default 100).
    """
    return _run_readonly_sql(
        case_manager,
        query=query,
        db_name=db_name,
        max_rows=max_rows,
    )


@mcp.tool()
def get_health_data(
    metric_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[HealthRecord]:
    """Retrieve health and biometric data (Steps, Heart Rate, Workouts, Sleep, etc.)."""
    return _get_health_data(
        case=case_manager,
        metric_type=metric_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def get_notes_and_memos(
    keyword: str | None = None,
    note_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[NoteRecord]:
    """Retrieve Apple Notes, Voice Memos, Reminders, and Calendar events."""
    return _get_notes_and_memos(
        case=case_manager,
        keyword=keyword,
        note_type=note_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def get_photos_metadata(
    has_gps: bool = False,
    is_deleted: bool = False,
    media_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[PhotoRecord]:
    """Retrieve photos, videos, and media metadata (EXIF)."""
    return _get_photos_metadata(
        case=case_manager,
        has_gps=has_gps,
        is_deleted=is_deleted,
        media_type=media_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def get_network_connections(
    connection_type: str | None = None,
    ssid_or_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[NetworkRecord]:
    """Retrieve wireless connections (Wi-Fi, Bluetooth, Cell Towers, AirDrop)."""
    return _get_network_connections(
        case=case_manager,
        connection_type=connection_type,
        ssid_or_name=ssid_or_name,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def get_system_state(
    event_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[SystemStateRecord]:
    """Retrieve system power state, lock cycles, and KnowledgeC/Biome events."""
    return _get_system_state(
        case=case_manager,
        event_type=event_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
