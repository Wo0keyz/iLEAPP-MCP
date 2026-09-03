import logging
import re
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import AppRecord, PaginatedResult

logger = logging.getLogger(__name__)


def _find_field(keys: list[str], raw: dict[str, Any]) -> Any | None:
    norm_targets = [re.sub(r"[\s_-]+", "", k.lower()) for k in keys]
    for raw_k, raw_v in raw.items():
        if raw_v is None or raw_v == "":
            continue
        raw_norm = re.sub(r"[\s_-]+", "", str(raw_k).lower())
        if raw_norm in norm_targets:
            return raw_v
    for raw_k, raw_v in raw.items():
        if raw_v is None or raw_v == "":
            continue
        raw_norm = re.sub(r"[\s_-]+", "", str(raw_k).lower())
        if any(target in raw_norm for target in norm_targets):
            return raw_v
    return None


def _normalize_app_record(raw: dict[str, Any]) -> AppRecord:
    """Normalize fields across installed apps, metadata, and permissions plugins."""
    name = _find_field(["App Name", "Application Name", "Name", "Display Name", "App"], raw)
    bundle_id = _find_field(
        ["Bundle ID", "Bundle Identifier", "Identifier", "App ID", "BundleId"], raw
    )
    version = _find_field(["Version", "App Version", "Short Version", "Bundle Version"], raw)
    install_date = _find_field(
        ["Install Date", "Date Installed", "Purchase Date", "Update Date", "Timestamp", "Date"], raw
    )
    developer = _find_field(["Developer", "Vendor", "Author", "Seller", "Developer Name"], raw)
    path = _find_field(["Path", "App Path", "Container", "Data Container", "Bundle Path"], raw)

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

    all_records: list[AppRecord] = []
    target_hints = [
        "installed_app",
        "applications",
        "apps",
        "app_permissions",
        "app_guid",
        "installed apps",
    ]

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
                        all_records.append(_normalize_app_record(row_dict))
            except Exception as e:
                logger.debug("Error reading apps from SQLite %s: %s", db_path, e)

    # 2. Search TSV files
    for tsv_path in case.get_all_tsv_files():
        stem = tsv_path.stem.lower()
        if any(t in stem for t in target_hints):
            rows = case.read_tsv_records(tsv_path)
            for r in rows:
                all_records.append(_normalize_app_record(r))

    # De-duplicate by bundle_id or app_name
    merged_map: dict[str, AppRecord] = {}
    for app in all_records:
        key = app.bundle_id or app.app_name or str(app.raw_data)
        if key not in merged_map:
            merged_map[key] = app
        else:
            # Merge extra metadata if missing
            existing = merged_map[key]
            if not existing.app_name and app.app_name:
                existing.app_name = app.app_name
            if not existing.version and app.version:
                existing.version = app.version
            if not existing.install_date and app.install_date:
                existing.install_date = app.install_date
            if app.permissions:
                for p in app.permissions:
                    if p not in existing.permissions:
                        existing.permissions.append(p)

    deduped = list(merged_map.values())

    # Apply filters
    filtered: list[AppRecord] = []
    for app in deduped:
        if app_name and (not app.app_name or app_name.lower() not in app.app_name.lower()):
            continue

        if bundle_id and (not app.bundle_id or bundle_id.lower() not in app.bundle_id.lower()):
            continue

        filtered.append(app)

    filtered.sort(key=lambda x: (x.app_name or x.bundle_id or "").lower())

    total_count = len(filtered)
    page = filtered[offset : offset + limit]
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
