import logging
import re
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import AppRecord, PaginatedResult

logger = logging.getLogger(__name__)


def _find_field(keys: list[str], raw: dict[str, Any]) -> Any | None:
    norm_raw = {
        re.sub(r"[\s_-]+", "", str(k).lower()): v
        for k, v in raw.items()
        if v is not None and v != ""
    }
    for k in keys:
        norm_k = re.sub(r"[\s_-]+", "", k.lower())
        if norm_k in norm_raw:
            return norm_raw[norm_k]
    for k in keys:
        norm_k = re.sub(r"[\s_-]+", "", k.lower())
        if len(norm_k) >= 3:
            for raw_k, raw_v in norm_raw.items():
                if norm_k in raw_k or raw_k in norm_k:
                    return raw_v
    return None


def _normalize_app_record(raw: dict[str, Any]) -> AppRecord:
    """Normalize fields across installed apps, metadata, and permissions plugins."""
    name = _find_field(
        [
            "Item Name",
            "App Name",
            "Application Name",
            "Display Name",
            "Name",
            "App",
            "Account Desc.",
        ],
        raw,
    )
    bundle_id = _find_field(
        ["Bundle ID", "Bundle Identifier", "Identifier", "App ID", "BundleId", "Parent Bundle ID"],
        raw,
    )
    version = _find_field(
        ["Version", "App Version", "Short Version", "Bundle Version", "From Version"],
        raw,
    )
    install_date = _find_field(
        [
            "Last Installed",
            "Install Date",
            "Date Installed",
            "Purchase Date",
            "Release Date",
            "Update Date",
            "Timestamp",
            "Date",
            "Last Seen",
        ],
        raw,
    )
    developer = _find_field(
        ["Artist Name", "Seller Name", "Developer", "Vendor", "Author", "Seller", "Developer Name"],
        raw,
    )
    path = _find_field(
        [
            "Path",
            "App Path",
            "Container",
            "Data Container",
            "Bundle Path",
            "Sandbox Path",
            "Event Path",
        ],
        raw,
    )

    perm_raw = _find_field(["Permissions", "Permission", "Granted Permissions", "Services"], raw)
    permissions = []
    if perm_raw and str(perm_raw).strip().lower() != "none":
        permissions = [p.strip() for p in str(perm_raw).replace(";", ",").split(",") if p.strip()]

    return AppRecord(
        app_name=str(name).strip() if name else None,
        bundle_id=str(bundle_id).strip() if bundle_id else None,
        version=str(version).strip() if version else None,
        install_date=str(install_date).strip() if install_date else None,
        developer=str(developer).strip() if developer else None,
        app_path=str(path).strip() if path else None,
        permissions=permissions,
        raw_data=raw,
    )


def get_installed_apps(
    case: CaseManager,
    app_name: str | None = None,
    bundle_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[AppRecord]:
    """Retrieve and inspect installed iOS applications, bundle identifiers, and permissions."""
    if not case.is_loaded:
        raise ValueError("No case loaded. Please call load_case first.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)

    target_hints = [
        "installed_app",
        "applications",
        "apps",
        "app_permissions",
        "app_guid",
        "installed apps",
        "itunes metadata",
        "itunesmeta",
        "applicationstate",
        "appgroup",
    ]

    merged_map: dict[str, AppRecord] = {}

    def process_row(r_dict: dict[str, Any]) -> None:
        rec = _normalize_app_record(r_dict)
        if not rec.bundle_id and not rec.app_name:
            return

        if app_name and (not rec.app_name or app_name.lower() not in rec.app_name.lower()):
            return
        if bundle_id and (not rec.bundle_id or bundle_id.lower() not in rec.bundle_id.lower()):
            return

        key = rec.bundle_id or rec.app_name or str(rec.raw_data)
        if key not in merged_map:
            merged_map[key] = rec
        else:
            existing = merged_map[key]
            if not existing.app_name and rec.app_name:
                existing.app_name = rec.app_name
            if not existing.version and rec.version:
                existing.version = rec.version
            if not existing.install_date and rec.install_date:
                existing.install_date = rec.install_date
            if not existing.developer and rec.developer:
                existing.developer = rec.developer
            if not existing.app_path and rec.app_path:
                existing.app_path = rec.app_path
            if rec.permissions:
                for p in rec.permissions:
                    if p not in existing.permissions:
                        existing.permissions.append(p)

    # 1. Search SQLite databases
    for db_path in case.get_all_sqlite_dbs():
        stem = db_path.stem.lower()
        if any(t in stem for t in target_hints):
            try:
                conn = case.get_sqlite_connection(db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                tables = [r[0] for r in cursor.fetchall()]
                for table in tables:
                    for row_dict in case.iter_sqlite_rows(db_path, f"SELECT * FROM `{table}`"):
                        process_row(row_dict)
            except Exception as e:
                logger.debug("Error reading apps from SQLite %s: %s", db_path, e)

    # 2. Search TSV files
    for tsv_path in case.get_all_tsv_files():
        stem = tsv_path.stem.lower()
        if any(t in stem for t in target_hints):
            try:
                for row_dict in case.iter_tsv_rows(tsv_path):
                    process_row(row_dict)
            except Exception as e:
                logger.debug("Error reading apps from TSV %s: %s", tsv_path, e)

    all_apps = list(merged_map.values())
    all_apps.sort(key=lambda x: (x.app_name or x.bundle_id or "").lower())

    total_count = len(all_apps)
    page = all_apps[offset : offset + limit]
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None

    return PaginatedResult[AppRecord](
        items=page,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
