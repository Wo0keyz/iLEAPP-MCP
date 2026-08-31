import logging
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import AppRecord, PaginatedResult

logger = logging.getLogger(__name__)


def _normalize_app_record(raw: dict[str, Any]) -> AppRecord:
    """Normalize fields across installed apps, metadata, and permissions plugins."""
    # Find app name
    name = None
    for k in ["App Name", "Application Name", "Name", "Display Name", "App"]:
        for raw_k, raw_v in raw.items():
            if k.lower() == raw_k.lower() and raw_v:
                name = str(raw_v).strip()
                break
        if name:
            break

    # Find bundle ID
    bundle_id = None
    for k in ["Bundle ID", "Bundle Identifier", "Identifier", "App ID", "BundleId"]:
        for raw_k, raw_v in raw.items():
            if k.lower() == raw_k.lower() and raw_v:
                bundle_id = str(raw_v).strip()
                break
        if bundle_id:
            break

    # Find version
    version = None
    for k in ["Version", "App Version", "Short Version", "Bundle Version"]:
        for raw_k, raw_v in raw.items():
            if k.lower() == raw_k.lower() and raw_v:
                version = str(raw_v).strip()
                break
        if version:
            break

    # Find install date
    install_date = None
    for k in [
        "Install Date",
        "Date Installed",
        "Purchase Date",
        "Update Date",
        "Timestamp",
        "Date",
    ]:
        for raw_k, raw_v in raw.items():
            if k.lower() == raw_k.lower() and raw_v:
                install_date = str(raw_v).strip()
                break
        if install_date:
            break

    # Find developer
    developer = None
    for k in ["Developer", "Vendor", "Author", "Seller", "Developer Name"]:
        for raw_k, raw_v in raw.items():
            if k.lower() == raw_k.lower() and raw_v:
                developer = str(raw_v).strip()
                break
        if developer:
            break

    # Find app path / sandbox
    path = None
    for k in ["Path", "App Path", "Container", "Data Container", "Bundle Path"]:
        for raw_k, raw_v in raw.items():
            if k.lower() == raw_k.lower() and raw_v:
                path = str(raw_v).strip()
                break
        if path:
            break

    # Find permissions
    permissions: list[str] = []
    for k in ["Permissions", "Permission", "Granted Permissions", "Services"]:
        for raw_k, raw_v in raw.items():
            if k.lower() == raw_k.lower() and raw_v:
                v_str = str(raw_v).strip()
                if v_str and v_str != "None":
                    parts = [p.strip() for p in v_str.replace(";", ",").split(",") if p.strip()]
                    permissions.extend(parts)

    return AppRecord(
        app_name=name,
        bundle_id=bundle_id,
        version=version,
        install_date=install_date,
        developer=developer,
        app_path=path,
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
    target_hints = ["installed_app", "applications", "apps", "app_permissions", "app_guid"]

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
