import logging
import re
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import HealthRecord, PaginatedResult

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


def get_health_data(
    case: CaseManager,
    metric_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[HealthRecord]:
    if not case.is_loaded:
        raise ValueError("No iLEAPP case loaded.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)
    results: list[HealthRecord] = []

    all_files = list(case.get_all_tsv_files()) + list(case.get_all_sqlite_dbs())
    for file_path in all_files:
        stem = file_path.stem
        name_low = stem.lower()
        if "health" in name_low or "biom" in name_low or "step" in name_low:
            if metric_type and metric_type.lower() not in name_low:
                continue

            try:
                if file_path.suffix.lower() in [".tsv", ".csv"]:
                    rows_to_process = case.read_tsv_records(file_path)
                else:
                    cols, r, total_c = case.query_sqlite(
                        file_path, f"SELECT * FROM `{stem}`", limit=10000, offset=0
                    )
                    rows_to_process = r

                for row in rows_to_process:
                    ts = _find_field(["timestamp", "date", "time", "start", "creation"], row)
                    if ts:
                        ts = str(ts)
                        if start_date and ts < start_date:
                            continue
                        if end_date and ts > end_date:
                            continue

                    mtype = _find_field(["metric", "type", "category", "name", "activity"], row)
                    if not mtype:
                        if "step" in name_low:
                            mtype = "Steps"
                        elif "heart" in name_low:
                            mtype = "Heart Rate"
                        elif "sleep" in name_low:
                            mtype = "Sleep"
                        else:
                            mtype = stem

                    val = _find_field(["value", "qty", "quantity", "count", "bpm", "duration"], row)
                    unit = _find_field(["unit", "measurement"], row)
                    source = _find_field(["source", "device", "hardware", "bundle"], row)

                    results.append(
                        HealthRecord(
                            timestamp=str(ts) if ts else None,
                            metric_type=str(mtype),
                            value=str(val) if val else None,
                            unit=str(unit) if unit else None,
                            source_device=str(source) if source else None,
                            raw_data=row,
                        )
                    )

            except Exception as e:
                logger.warning(f"Error querying health artifact {stem}: {e}")

    total_count = len(results)
    paginated_items = results[offset : offset + limit]
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None

    return PaginatedResult[HealthRecord](
        items=paginated_items,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
