import contextlib
import logging
import math
import re
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import PaginatedResult, PhotoRecord

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


def get_photos_metadata(
    case: CaseManager,
    has_gps: bool = False,
    is_deleted: bool = False,
    media_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[PhotoRecord]:
    """Retrieve EXIF metadata, camera models, GPS tags, and album associations for captured media."""
    if not case.is_loaded:
        raise ValueError("No case loaded.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)

    target_hints = ["photo", "media", "exif", "album", "zasset", "camera"]

    seen = set()
    filtered: list[PhotoRecord] = []
    total_count = 0

    def process_row(row: dict[str, Any], file_stem: str) -> None:
        nonlocal total_count
        name_low = file_stem.lower()

        ts = _find_field(
            [
                "Date/Time Original",
                "Timestamp",
                "Date",
                "Creation Date",
                "Creation",
                "Added Date",
                "Added",
            ],
            row,
        )
        ts_str = str(ts).strip() if ts else None
        if start_date and ts_str and ts_str < start_date:
            return
        if end_date and ts_str and ts_str > end_date:
            return

        lat_raw = _find_field(["Latitude", "Lat", "GPS Latitude"], row)
        lon_raw = _find_field(["Longitude", "Lon", "GPS Longitude"], row)

        lat: float | None = None
        if lat_raw is not None:
            with contextlib.suppress(ValueError):
                parsed = float(str(lat_raw).strip())
                if not math.isnan(parsed) and not math.isinf(parsed) and -90.0 <= parsed <= 90.0:
                    lat = parsed

        lon: float | None = None
        if lon_raw is not None:
            with contextlib.suppress(ValueError):
                parsed = float(str(lon_raw).strip())
                if not math.isnan(parsed) and not math.isinf(parsed) and -180.0 <= parsed <= 180.0:
                    lon = parsed

        if has_gps and (lat is None or lon is None):
            return

        deleted_flag = _find_field(["Deleted", "Trash", "Trashed", "Is Deleted"], row)
        is_del = (
            bool(deleted_flag and str(deleted_flag).lower() not in {"0", "false", "no"})
            if deleted_flag
            else ("trash" in name_low or "delete" in name_low)
        )
        if is_deleted and not is_del:
            return

        mtype = _find_field(["Media Type", "Type", "Kind"], row) or "Image"
        mtype_str = str(mtype).strip()
        if media_type and media_type.lower() not in mtype_str.lower():
            return

        fname = _find_field(["Filename", "File Name", "Name", "Original Filename", "Original"], row)
        cam = _find_field(["Camera", "Model", "Make", "Camera Model", "Lens"], row)
        album = _find_field(["Album", "Album Name", "Folder", "Directory"], row)
        fpath = _find_field(["Path", "File Path", "File", "Location", "URI"], row)

        fname_str = str(fname).strip() if fname else None
        cam_str = str(cam).strip() if cam else None
        album_str = str(album).strip() if album else None
        fpath_str = str(fpath).strip() if fpath else None

        if not fname_str and not fpath_str and lat is None and lon is None:
            return

        key = (ts_str or "", fname_str or "", fpath_str or "", lat, lon)
        if key not in seen:
            seen.add(key)
            total_count += 1
            if len(filtered) < offset + limit:
                filtered.append(
                    PhotoRecord(
                        timestamp=ts_str,
                        file_name=fname_str,
                        media_type=mtype_str,
                        latitude=lat,
                        longitude=lon,
                        camera_model=cam_str,
                        is_deleted=is_del,
                        album_name=album_str,
                        file_path=fpath_str,
                        raw_data=row,
                    )
                )

    # 1. Search SQLite databases
    for db_path in case.get_all_sqlite_dbs():
        stem = db_path.stem.lower()
        if any(h in stem for h in target_hints):
            try:
                conn = case.get_sqlite_connection(db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                tables = [r[0] for r in cursor.fetchall()]
                for tbl in tables:
                    for row_dict in case.iter_sqlite_rows(db_path, f"SELECT * FROM `{tbl}`"):
                        process_row(row_dict, db_path.stem)
            except Exception as e:
                logger.debug("Error reading photos SQLite %s: %s", db_path, e)

    # 2. Search TSV files
    for tsv_path in case.get_all_tsv_files():
        stem = tsv_path.stem.lower()
        if any(h in stem for h in target_hints):
            try:
                for row_dict in case.iter_tsv_rows(tsv_path):
                    process_row(row_dict, tsv_path.stem)
            except Exception as e:
                logger.debug("Error reading photos TSV %s: %s", tsv_path, e)

    filtered.sort(key=lambda x: x.timestamp or "")

    page = filtered[offset : offset + limit]
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None

    return PaginatedResult[PhotoRecord](
        items=page,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
