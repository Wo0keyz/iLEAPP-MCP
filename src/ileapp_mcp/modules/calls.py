import contextlib
import logging
import re
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import CallRecord, PaginatedResult

logger = logging.getLogger(__name__)


def _find_field(keys: list[str], raw: dict[str, Any]) -> Any | None:
    """Find a value in raw dictionary matching any key in keys (case- and delimiter-insensitive)."""
    norm_targets = [re.sub(r"[\s_-]+", "", k.lower()) for k in keys]
    for raw_k, raw_v in raw.items():
        if raw_v is None or raw_v == "":
            continue
        raw_norm = re.sub(r"[\s_-]+", "", str(raw_k).lower())
        if raw_norm in norm_targets:
            return raw_v
    # Secondary check: partial substring
    for raw_k, raw_v in raw.items():
        if raw_v is None or raw_v == "":
            continue
        raw_norm = re.sub(r"[\s_-]+", "", str(raw_k).lower())
        for nt in norm_targets:
            if nt in raw_norm or raw_norm in nt:
                return raw_v
    return None


def _normalize_call_record(raw: dict[str, Any], default_app: str = "Cellular") -> CallRecord:
    """Normalize fields across different iLEAPP call history plugins and schemas."""
    ts = _find_field(["Call Date", "Date", "Timestamp", "Start Time", "Time", "Date/Time"], raw)
    ts_str = str(ts).strip() if ts else None

    number = _find_field(
        ["Phone Number", "Number", "Caller", "Address", "Handle", "Recipient", "Contact ID"], raw
    )
    number_str = str(number).strip() if number else None

    name = _find_field(["Contact Name", "Name", "Caller Name", "Display Name"], raw)
    name_str = str(name).strip() if name and str(name).lower() not in {"none", "null"} else None

    call_type_raw = _find_field(["Call Type", "Type", "Status", "Direction"], raw)
    call_type = "Unknown"
    if call_type_raw:
        v_str = str(call_type_raw).strip()
        if "miss" in v_str.lower():
            call_type = "Missed"
        elif "in" in v_str.lower() or v_str == "1":
            call_type = "Incoming"
        elif "out" in v_str.lower() or v_str == "2":
            call_type = "Outgoing"
        elif "reject" in v_str.lower() or "cancel" in v_str.lower():
            call_type = "Rejected"
        else:
            call_type = v_str

    duration_raw = _find_field(["Duration", "Duration Seconds", "Call Duration", "Length"], raw)
    duration = None
    if duration_raw is not None:
        v_str = str(duration_raw).strip()
        if ":" in v_str:
            parts = v_str.split(":")
            try:
                if len(parts) == 2:
                    duration = int(parts[0]) * 60 + int(parts[1])
                elif len(parts) == 3:
                    duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            except ValueError:
                pass
        else:
            m = re.search(r"\d+", v_str)
            if m:
                with contextlib.suppress(ValueError):
                    duration = int(m.group(0))

    app_raw = _find_field(["Service", "App", "Source", "Protocol"], raw)
    app = str(app_raw).strip() if app_raw else default_app

    return CallRecord(
        timestamp=ts_str,
        app=app,
        call_type=call_type,
        phone_number=number_str,
        contact_name=name_str,
        duration_seconds=duration,
        raw_data=raw,
    )


def get_call_history(
    case: CaseManager,
    phone_number: str | None = None,
    call_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[CallRecord]:
    """Retrieve and filter call logs (Cellular, FaceTime, VoIP) with duration and contact details."""
    if not case.is_loaded:
        raise ValueError("No case loaded. Please call load_case first.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)

    target_hints = ["call_history", "calls", "facetime", "voip", "call"]

    seen = set()
    filtered: list[CallRecord] = []
    total_count = 0

    def process_row(r_dict: dict[str, Any], db_app: str) -> None:
        nonlocal total_count
        c = _normalize_call_record(r_dict, default_app=db_app)

        if phone_number:
            p_low = phone_number.lower()
            num_match = c.phone_number and p_low in c.phone_number.lower()
            name_match = c.contact_name and p_low in c.contact_name.lower()
            if not (num_match or name_match):
                return
        if call_type and (not c.call_type or call_type.lower() not in c.call_type.lower()):
            return
        if start_date and c.timestamp and c.timestamp < start_date:
            return
        if end_date and c.timestamp and c.timestamp > end_date:
            return

        key = (c.timestamp or "", c.phone_number or "", c.call_type or "", c.duration_seconds)
        if key not in seen:
            seen.add(key)
            total_count += 1
            if len(filtered) < offset + limit:
                filtered.append(c)

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
                    default_app = "FaceTime" if "facetime" in stem else "Cellular"
                    for row_dict in case.iter_sqlite_rows(db_path, f"SELECT * FROM `{table}`"):
                        process_row(row_dict, default_app)
            except Exception as e:
                logger.debug("Error reading calls from SQLite %s: %s", db_path, e)

    # 2. Search TSV files
    for tsv_path in case.get_all_tsv_files():
        stem = tsv_path.stem.lower()
        if any(t in stem for t in target_hints):
            default_app = "FaceTime" if "facetime" in stem else "Cellular"
            rows = case.read_tsv_records(tsv_path)
            for r in rows:
                process_row(r, default_app)

    filtered.sort(key=lambda x: x.timestamp or "")

    page = filtered[offset : offset + limit]
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None

    return PaginatedResult[CallRecord](
        items=page,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
