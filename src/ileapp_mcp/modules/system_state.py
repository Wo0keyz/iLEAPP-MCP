import logging
import re
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import PaginatedResult, SystemStateRecord

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


def get_system_state(
    case: CaseManager,
    event_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[SystemStateRecord]:
    """Retrieve system lifecycle events (power on/off, battery levels, device lock/unlock, screen on/off)."""
    if not case.is_loaded:
        raise ValueError("No case loaded.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)

    target_hints = [
        "power",
        "battery",
        "lock",
        "knowledgec",
        "biome",
        "reboot",
        "sysdiag",
        "state",
        "screen",
    ]

    seen = set()
    filtered: list[SystemStateRecord] = []
    total_count = 0

    def process_row(row: dict[str, Any], file_stem: str) -> None:
        nonlocal total_count
        name_low = file_stem.lower()

        ts = _find_field(
            [
                "Timestamp",
                "Date",
                "Time",
                "Creation Date",
                "Start Time",
                "Event Timestamp",
                "SEGB Timestamp",
                "Time Write",
            ],
            row,
        )
        ts_str = str(ts).strip() if ts else None
        if start_date and ts_str and ts_str < start_date:
            return
        if end_date and ts_str and ts_str > end_date:
            return

        etype = "System Event"
        if "battery" in name_low or "power" in name_low:
            etype = "Battery/Power"
        elif "lock" in name_low:
            etype = "Lock/Unlock"
        elif "screen" in name_low:
            etype = "Screen State"
        elif "reboot" in name_low or "sysdiag" in name_low or "boot" in name_low:
            etype = "Reboot/Boot"
        elif "knowledgec" in name_low or "biome" in name_low:
            etype = "KnowledgeC/Biome"

        if (
            event_type
            and event_type.lower() not in etype.lower()
            and event_type.lower() not in name_low
        ):
            return

        val = _find_field(
            [
                "Value",
                "State",
                "Level",
                "Battery Level",
                "Battery Percentage",
                "Status",
                "Event",
                "Bundle ID",
                "App",
                "Description",
            ],
            row,
        )
        val_str = str(val).strip() if val is not None else None

        key = (ts_str or "", etype, val_str or "")
        if key not in seen:
            seen.add(key)
            total_count += 1
            if len(filtered) < offset + limit:
                filtered.append(
                    SystemStateRecord(
                        timestamp=ts_str,
                        event_type=etype,
                        value=val_str,
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
                logger.debug("Error reading system state SQLite %s: %s", db_path, e)

    # 2. Search TSV files
    for tsv_path in case.get_all_tsv_files():
        stem = tsv_path.stem.lower()
        if any(h in stem for h in target_hints):
            try:
                for row_dict in case.iter_tsv_rows(tsv_path):
                    process_row(row_dict, tsv_path.stem)
            except Exception as e:
                logger.debug("Error reading system state TSV %s: %s", tsv_path, e)

    filtered.sort(key=lambda x: x.timestamp or "")

    page = filtered[offset : offset + limit]
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None

    return PaginatedResult[SystemStateRecord](
        items=page,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
