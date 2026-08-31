import logging
import re
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import PaginatedResult, SystemStateRecord

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


def get_system_state(
    case: CaseManager,
    event_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[SystemStateRecord]:
    if not case.is_loaded:
        raise ValueError("No case loaded.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)
    results: list[SystemStateRecord] = []
    global_total_count = 0

    all_files = list(case.get_all_tsv_files()) + list(case.get_all_sqlite_dbs())
    for file_path in all_files:
        stem = file_path.stem
        name_low = stem.lower()
        if any(
            x in name_low
            for x in [
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
        ):
            if event_type and event_type.lower() not in name_low:
                continue

            try:
                if file_path.suffix.lower() in [".tsv", ".csv"]:
                    rows_iterator = case.iter_tsv_rows(file_path)
                else:
                    rows_iterator = case.iter_sqlite_rows(file_path, f"SELECT * FROM `{stem}`")

                for row in rows_iterator:
                    ts = _find_field(["timestamp", "date", "time", "creation"], row)
                    if ts:
                        ts = str(ts)
                        if start_date and ts < start_date:
                            continue
                        if end_date and ts > end_date:
                            continue

                    etype = "System Event"
                    if "battery" in name_low or "power" in name_low:
                        etype = "Battery/Power"
                    elif "lock" in name_low:
                        etype = "Lock/Unlock"
                    elif "knowledgec" in name_low or "biome" in name_low:
                        etype = "KnowledgeC/Biome"
                    elif "reboot" in name_low or "sysdiag" in name_low:
                        etype = "Reboot/Boot"
                    elif "screen" in name_low:
                        etype = "Screen State"

                    if event_type and event_type.lower() not in etype.lower():
                        continue

                    val = _find_field(
                        ["value", "state", "level", "bundle", "app", "status", "batterylevel"], row
                    )

                    if offset <= global_total_count < offset + limit:
                        results.append(
                            SystemStateRecord(
                                timestamp=str(ts) if ts else None,
                                event_type=etype,
                                value=str(val) if val else None,
                                raw_data=row,
                            )
                        )
                    global_total_count += 1

            except Exception as e:
                logger.warning(f"Error querying system state artifact {stem}: {e}")

    total_count = global_total_count
    paginated_items = results
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None

    return PaginatedResult[SystemStateRecord](
        items=paginated_items,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
