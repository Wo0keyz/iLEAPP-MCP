import logging
import re
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import PaginatedResult, PhotoRecord

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
    if not case.is_loaded:
        raise ValueError("No case loaded.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)
    results: list[PhotoRecord] = []

    all_files = list(case.get_all_tsv_files()) + list(case.get_all_sqlite_dbs())
    for file_path in all_files:
        stem = file_path.stem
        name_low = stem.lower()
        if any(x in name_low for x in ["photo", "media", "exif", "album", "zasset"]):
            try:
                if file_path.suffix.lower() in [".tsv", ".csv"]:
                    rows_to_process = case.read_tsv_records(file_path)
                else:
                    try:
                        conn = case.get_sqlite_connection(file_path)
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        )
                        tables = [r[0] for r in cursor.fetchall()]
                    except Exception:
                        tables = [stem]

                    rows_to_process = []
                    for tbl in tables:
                        if not rows_to_process:
                            cols, r, total_c = case.query_sqlite(
                                file_path, f"SELECT * FROM `{tbl}`", limit=10000, offset=0
                            )
                            rows_to_process = r

                if rows_to_process:
                    for row in rows_to_process:
                        ts = _find_field(["timestamp", "date", "creation", "added"], row)
                        if ts:
                            ts = str(ts)
                            if start_date and ts < start_date:
                                continue
                            if end_date and ts > end_date:
                                continue

                        lat = _find_field(["latitude", "lat"], row)
                        lon = _find_field(["longitude", "lon"], row)
                        if has_gps and (lat is None or lon is None):
                            continue

                        deleted_flag = _find_field(["deleted", "trash", "trashed"], row)
                        is_del = (
                            bool(deleted_flag)
                            if deleted_flag
                            else ("trash" in name_low or "delete" in name_low)
                        )
                        if is_deleted and not is_del:
                            continue

                        mtype = _find_field(["type", "media_type", "kind"], row) or "Image"
                        if media_type and media_type.lower() not in str(mtype).lower():
                            continue

                        fname = _find_field(["filename", "name", "original"], row)
                        cam = _find_field(["camera", "model", "make", "lens"], row)
                        album = _find_field(["album", "folder", "directory"], row)
                        fpath = _find_field(["path", "file", "location", "uri"], row)

                        results.append(
                            PhotoRecord(
                                timestamp=str(ts) if ts else None,
                                file_name=str(fname) if fname else None,
                                media_type=str(mtype),
                                latitude=float(lat) if lat else None,
                                longitude=float(lon) if lon else None,
                                camera_model=str(cam) if cam else None,
                                is_deleted=is_del,
                                album_name=str(album) if album else None,
                                file_path=str(fpath) if fpath else None,
                                raw_data=row,
                            )
                        )

            except Exception as e:
                logger.warning(f"Error querying photos artifact {stem}: {e}")

    total_count = len(results)
    paginated_items = results[offset : offset + limit]
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None

    return PaginatedResult[PhotoRecord](
        items=paginated_items,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
