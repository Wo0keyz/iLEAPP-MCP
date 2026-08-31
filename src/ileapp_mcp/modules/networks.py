import logging
import re
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import NetworkRecord, PaginatedResult

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


def get_network_connections(
    case: CaseManager,
    connection_type: str | None = None,
    ssid_or_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[NetworkRecord]:
    if not case.is_loaded:
        raise ValueError("No case loaded.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)
    results = []
    total = 0

    all_files = list(case.get_all_tsv_files()) + list(case.get_all_sqlite_dbs())
    for file_path in all_files:
        stem = file_path.stem
        name_low = stem.lower()
        if any(
            x in name_low
            for x in ["wifi", "wi-fi", "bluetooth", "cell", "network", "airdrop", "wlan"]
        ):
            if connection_type and connection_type.lower() not in name_low:
                continue

            try:
                if file_path.suffix.lower() in [".tsv", ".csv"]:
                    rows = case.read_tsv_records(file_path)

                    class DummyPage:
                        def __init__(self, r):
                            self.rows = r[offset : offset + limit]
                            self.total_count = len(r)

                    page = DummyPage(rows)
                else:
                    cols, r, total_c = case.query_sqlite(
                        file_path, f"SELECT * FROM `{stem}`", limit=10000, offset=0
                    )

                    class DummyPage2:
                        def __init__(self, ro, tc):
                            self.rows = ro
                            self.total_count = tc

                    page = DummyPage2(r, total_c)

                for row in page.rows:
                    ts = _find_field(
                        ["timestamp", "date", "time", "lastconnected", "joined", "lastjoined"], row
                    )
                    if ts:
                        ts = str(ts)
                        if start_date and ts < start_date:
                            continue
                        if end_date and ts > end_date:
                            continue

                    name = _find_field(["ssid", "name", "device", "network"], row)
                    if (
                        ssid_or_name
                        and ssid_or_name.lower() not in str(name).lower()
                        and ssid_or_name.lower() not in name_low
                    ):
                        continue

                    mac = _find_field(["bssid", "mac", "address"], row)
                    dur = _find_field(["duration", "timeconnected"], row)

                    ctype = "Wi-Fi"
                    if "bluetooth" in name_low:
                        ctype = "Bluetooth"
                    elif "cell" in name_low:
                        ctype = "Cell Tower"
                    elif "airdrop" in name_low:
                        ctype = "AirDrop"

                    results.append(
                        NetworkRecord(
                            timestamp=str(ts) if ts else None,
                            connection_type=ctype,
                            ssid_or_name=str(name) if name else None,
                            bssid_or_mac=str(mac) if mac else None,
                            duration_seconds=int(dur) if dur and str(dur).isdigit() else None,
                            raw_data=row,
                        )
                    )

            except Exception as e:
                logger.warning(f"Error querying network artifact {stem}: {e}")

    total_count = len(results)
    page = results[offset : offset + limit]
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None

    return PaginatedResult[NetworkRecord](
        items=page,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
