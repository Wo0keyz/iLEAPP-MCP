import contextlib
import logging
import re
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import NetworkRecord, PaginatedResult

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


def get_network_connections(
    case: CaseManager,
    connection_type: str | None = None,
    ssid_or_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[NetworkRecord]:
    """Retrieve wireless connection history (Wi-Fi networks, Bluetooth pairings, Cell towers, AirDrop)."""
    if not case.is_loaded:
        raise ValueError("No case loaded.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)

    target_hints = [
        "wifi",
        "wi-fi",
        "bluetooth",
        "cell",
        "network",
        "airdrop",
        "wlan",
        "bssid",
        "ssid",
    ]

    seen = set()
    filtered: list[NetworkRecord] = []
    total_count = 0

    def process_row(row: dict[str, Any], file_stem: str) -> None:
        nonlocal total_count
        name_low = file_stem.lower()

        ts = _find_field(
            [
                "Last Joined",
                "Last Updated",
                "Last Auto Joined",
                "Added At",
                "Last Associated/Roamed At",
                "Timestamp",
                "Date",
                "Last Connection Timestamp",
                "SEGB Timestamp",
                "Joined",
                "Last Connected",
                "Time",
            ],
            row,
        )
        ts_str = str(ts).strip() if ts else None
        if start_date and ts_str and ts_str < start_date:
            return
        if end_date and ts_str and ts_str > end_date:
            return

        name = _find_field(
            [
                "SSID",
                "Device Name",
                "User Defined Name",
                "Device",
                "Name",
                "Network Name",
                "Carrier",
                "Airdrop ID",
            ],
            row,
        )
        name_str = str(name).strip() if name else None

        if (
            ssid_or_name
            and (not name_str or ssid_or_name.lower() not in name_str.lower())
            and ssid_or_name.lower() not in name_low
        ):
            return

        mac = _find_field(["BSSID", "MAC Address", "MAC", "Address", "BSD Name"], row)
        dur = _find_field(["Duration", "Time Connected", "Network Usage"], row)

        ctype = "Wi-Fi"
        if "bluetooth" in name_low:
            ctype = "Bluetooth"
        elif "cell" in name_low:
            ctype = "Cell Tower"
        elif "airdrop" in name_low:
            ctype = "AirDrop"

        if (
            connection_type
            and connection_type.lower() not in ctype.lower()
            and connection_type.lower() not in name_low
        ):
            return

        mac_str = str(mac).strip() if mac else None
        dur_val: int | None = None
        if dur:
            m = re.search(r"\d+", str(dur))
            if m:
                with contextlib.suppress(ValueError):
                    dur_val = int(m.group(0))

        key = (ts_str or "", ctype, name_str or "", mac_str or "")
        if key not in seen:
            seen.add(key)
            total_count += 1
            if len(filtered) < offset + limit:
                filtered.append(
                    NetworkRecord(
                        timestamp=ts_str,
                        connection_type=ctype,
                        ssid_or_name=name_str,
                        bssid_or_mac=mac_str,
                        duration_seconds=dur_val,
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
                logger.debug("Error reading network SQLite %s: %s", db_path, e)

    # 2. Search TSV files
    for tsv_path in case.get_all_tsv_files():
        stem = tsv_path.stem.lower()
        if any(h in stem for h in target_hints):
            try:
                for row_dict in case.iter_tsv_rows(tsv_path):
                    process_row(row_dict, tsv_path.stem)
            except Exception as e:
                logger.debug("Error reading network TSV %s: %s", tsv_path, e)

    filtered.sort(key=lambda x: x.timestamp or "")

    page = filtered[offset : offset + limit]
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
