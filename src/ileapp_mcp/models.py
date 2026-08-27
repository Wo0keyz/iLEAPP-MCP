from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResult(BaseModel, Generic[T]):
    """Standard pagination envelope for all list responses."""

    items: list[T] = Field(description="List of records for the current page")
    total_count: int = Field(description="Total number of records matching the query")
    has_more: bool = Field(description="Whether more records are available beyond this page")
    limit: int = Field(description="Requested page size limit")
    offset: int = Field(description="Current record offset")
    next_offset: int | None = Field(
        default=None, description="Offset to use for the next page, or None if last page"
    )


class DeviceInfo(BaseModel):
    """Forensic metadata and hardware info of the extracted iOS device."""

    device_name: str | None = Field(default=None, description="Device name (e.g. iPhone de John)")
    ios_version: str | None = Field(default=None, description="iOS firmware version (e.g. 17.4.1)")
    product_type: str | None = Field(
        default=None, description="Model identifier (e.g. iPhone14,2 / iPhone 13 Pro)"
    )
    serial_number: str | None = Field(default=None, description="Hardware serial number")
    imei: str | None = Field(default=None, description="IMEI number(s)")
    phone_number: str | None = Field(default=None, description="Configured phone number")
    timezone: str | None = Field(default=None, description="Device configured timezone")
    extraction_type: str | None = Field(
        default=None, description="Extraction format (FFS, GrayKey, iTunes Backup, etc.)"
    )
    extraction_date: str | None = Field(
        default=None, description="Date/time when the extraction was generated"
    )
    raw_metadata: dict[str, str] = Field(
        default_factory=dict, description="All raw key-value metadata parsed from iLEAPP"
    )


class MessageRecord(BaseModel):
    """Forensic record for messages (SMS, iMessage, WhatsApp, Telegram, etc.)."""

    timestamp: str | None = Field(default=None, description="Message timestamp in ISO/UTC format")
    app: str = Field(description="Source application (e.g. iMessage, SMS, WhatsApp)")
    sender: str | None = Field(default=None, description="Sender identifier, number, or name")
    recipient: str | None = Field(
        default=None, description="Recipient identifier(s), number, or group"
    )
    message_text: str | None = Field(default=None, description="Text content of the message")
    direction: str | None = Field(
        default=None, description="Direction (Incoming, Outgoing, System)"
    )
    is_read: bool | None = Field(default=None, description="Read receipt status")
    attachment_count: int = Field(default=0, description="Number of attached media/files")
    attachment_paths: list[str] = Field(
        default_factory=list, description="Relative paths or descriptions of attachments"
    )
    raw_data: dict[str, Any] = Field(
        default_factory=dict, description="Full raw fields from the iLEAPP report"
    )


class CallRecord(BaseModel):
    """Forensic record for phone and VoIP calls (Cellular, FaceTime, WhatsApp, etc.)."""

    timestamp: str | None = Field(default=None, description="Call start timestamp in ISO format")
    app: str = Field(default="Cellular", description="Service used (Cellular, FaceTime, WhatsApp)")
    call_type: str | None = Field(
        default=None, description="Type of call (Incoming, Outgoing, Missed, Rejected)"
    )
    phone_number: str | None = Field(
        default=None, description="Phone number or account ID of counterparty"
    )
    contact_name: str | None = Field(
        default=None, description="Resolved contact name if present in call log"
    )
    duration_seconds: int | None = Field(default=None, description="Call duration in seconds")
    raw_data: dict[str, Any] = Field(
        default_factory=dict, description="Raw fields from the iLEAPP report"
    )


class LocationRecord(BaseModel):
    """Forensic record for geographical locations and significant places."""

    timestamp: str | None = Field(default=None, description="Timestamp of the location record")
    latitude: float | None = Field(default=None, description="Latitude in decimal degrees")
    longitude: float | None = Field(default=None, description="Longitude in decimal degrees")
    altitude: float | None = Field(default=None, description="Altitude in meters")
    horizontal_accuracy: float | None = Field(
        default=None, description="Estimated accuracy in meters"
    )
    source_type: str = Field(
        default="GPS",
        description="Source provider (Significant Locations, Routine, Apple Maps, Cell Tower, Wi-Fi)",
    )
    description: str | None = Field(
        default=None, description="Address, place name, or visit duration details"
    )
    raw_data: dict[str, Any] = Field(
        default_factory=dict, description="Raw fields from the iLEAPP report"
    )


class WebRecord(BaseModel):
    """Forensic record for web browsing activity (Safari, Chrome, etc.)."""

    timestamp: str | None = Field(default=None, description="Timestamp of the web activity")
    browser: str = Field(default="Safari", description="Web browser (Safari, Chrome, etc.)")
    record_type: str = Field(
        default="history", description="Type of record (history, search, download, bookmark, tab)"
    )
    url: str | None = Field(default=None, description="Full URL visited or referenced")
    title: str | None = Field(default=None, description="Page title")
    visit_count: int | None = Field(
        default=None, description="Number of times the page was visited"
    )
    search_term: str | None = Field(
        default=None, description="Extracted search term if query was a web search"
    )
    raw_data: dict[str, Any] = Field(
        default_factory=dict, description="Raw fields from the iLEAPP report"
    )


class AppRecord(BaseModel):
    """Forensic record for an installed application or app usage event."""

    app_name: str | None = Field(default=None, description="Display name of the application")
    bundle_id: str | None = Field(
        default=None, description="Bundle identifier (e.g. com.apple.mobilesafari)"
    )
    version: str | None = Field(default=None, description="Installed version")
    install_date: str | None = Field(default=None, description="Installation or update date")
    developer: str | None = Field(default=None, description="App developer name")
    app_path: str | None = Field(default=None, description="Filesystem sandbox path")
    permissions: list[str] = Field(
        default_factory=list, description="Granted permissions (Camera, Location, Contacts, etc.)"
    )
    raw_data: dict[str, Any] = Field(
        default_factory=dict, description="Raw fields from the iLEAPP report"
    )


class TimelineEvent(BaseModel):
    """Chronological event unified across multiple forensic artifact sources."""

    timestamp: str = Field(description="ISO 8601 formatted event timestamp (UTC)")
    category: str = Field(
        description="Forensic category (messages, calls, web, locations, apps, system)"
    )
    source_artifact: str = Field(
        description="Original artifact name or table (e.g. SMS_&_iMessage, Safari_History)"
    )
    summary: str = Field(description="Human-readable brief summary of the event")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Detailed attributes of the event"
    )


class ArtifactInfo(BaseModel):
    """Metadata describing a parsed artifact discovered in the iLEAPP report directory."""

    name: str = Field(description="Artifact / Table / File name")
    category: str = Field(description="Logical forensic category")
    format: str = Field(description="Underlying format (sqlite, tsv, csv, html, json)")
    file_path: str = Field(description="Relative path to the artifact file")
    row_count: int | None = Field(
        default=None, description="Number of parsed records in this artifact"
    )
    description: str | None = Field(default=None, description="Description of the artifact purpose")


class SqlQueryResult(BaseModel):
    """Result of a read-only SQL query execution."""

    query: str = Field(description="Executed SQL query")
    db_name: str = Field(description="Database file targeted")
    columns: list[str] = Field(description="Column names returned by the query")
    rows: list[dict[str, Any]] = Field(description="Row records returned (limited to max limit)")
    row_count: int = Field(description="Number of rows returned in this response")
    truncated: bool = Field(
        default=False, description="True if results were truncated to the maximum limit"
    )


class CaseInfo(BaseModel):
    """Overview and status of the currently loaded iLEAPP case directory."""

    case_path: str = Field(description="Filesystem path of the loaded case directory")
    loaded: bool = Field(description="Whether the case is successfully loaded and validated")
    total_artifacts: int = Field(description="Total number of discovered artifact tables/files")
    sqlite_databases: list[str] = Field(
        default_factory=list, description="List of discovered SQLite databases"
    )
    tsv_files: list[str] = Field(default_factory=list, description="List of discovered TSV files")
    device_summary: dict[str, str] = Field(
        default_factory=dict, description="Summary of device information"
    )
