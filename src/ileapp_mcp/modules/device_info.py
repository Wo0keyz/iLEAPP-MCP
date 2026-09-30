import logging
import re
from typing import Any

from ileapp_mcp.case import CaseManager, evidence_fields
from ileapp_mcp.models import DeviceInfo

logger = logging.getLogger(__name__)


def get_device_info(case: CaseManager) -> DeviceInfo:
    """Extract hardware, iOS version, serial, and case metadata from the iLEAPP report."""
    if not case.is_loaded or not case.case_path:
        raise ValueError("No iLEAPP case is currently loaded. Use load_case first.")

    raw_meta: dict[str, str] = {}
    raw_src: dict[str, dict[str, Any]] = {}  # key of raw_meta -> provenance of its row

    def put(key: str, value: str, row: Any, overwrite: bool = True) -> None:
        if overwrite or key not in raw_meta:
            raw_meta[key] = value
            raw_src[key] = evidence_fields(row)

    # 1. Look for TSV files related to device info / system info
    tsv_hints = [
        "device_information",
        "system_info",
        "device_info",
        "build_info",
        "device_details",
        "sys_info",
        "ios information",
        "device data",
        "device name",
        "subscriber info",
        "account data",
        "cellular wireless",
        "biome - device metadata",
        "biome - device timezone",
        "connected device information - current device information",
        "activator",
    ]

    for hint in tsv_hints:
        tsv_path = case.get_tsv_path(hint)
        if tsv_path:
            records = case.read_tsv_records(tsv_path)
            for r in records:
                # Handle Key/Value structure or wide row structure
                if "Key" in r and "Value" in r:
                    put(r["Key"].strip(), r["Value"].strip(), r)
                elif "Property" in r and "Value" in r:
                    put(r["Property"].strip(), r["Value"].strip(), r)
                elif "Property" in r and "Property Value" in r:
                    put(r["Property"].strip(), r["Property Value"].strip(), r)
                elif "Parameter" in r and "Value" in r:
                    put(r["Parameter"].strip(), r["Value"].strip(), r)
                else:
                    for k, v in r.items():
                        if k and v:
                            put(k.strip(), str(v).strip(), r)

    # 2. Check if a SQLite database contains system/device info table
    for db_path in case.get_all_sqlite_dbs():
        db_name = db_path.stem.lower()
        if any(h in db_name for h in ["device", "system", "report", "sys", "metadata"]):
            try:
                conn = case.get_sqlite_connection(db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%info%' OR name LIKE '%device%' OR name LIKE '%system%' OR name LIKE '%meta%')"
                )
                tables = [row[0] for row in cursor.fetchall()]
                for tbl in tables:
                    for row_dict in case.iter_sqlite_rows(
                        db_path, f"SELECT * FROM `{tbl}` LIMIT 100"
                    ):
                        if "Key" in row_dict and "Value" in row_dict:
                            put(
                                str(row_dict["Key"]).strip(),
                                str(row_dict["Value"]).strip(),
                                row_dict,
                            )
                        elif "Property" in row_dict and "Value" in row_dict:
                            put(
                                str(row_dict["Property"]).strip(),
                                str(row_dict["Value"]).strip(),
                                row_dict,
                            )
                        elif "Property" in row_dict and "Property Value" in row_dict:
                            put(
                                str(row_dict["Property"]).strip(),
                                str(row_dict["Property Value"]).strip(),
                                row_dict,
                            )
                        else:
                            for k, v in row_dict.items():
                                if k and v is not None and str(k) not in raw_meta:
                                    put(str(k).strip(), str(v).strip(), row_dict)
            except Exception as e:
                logger.warning("Error inspecting SQLite DB %s for device info: %s", db_path, e)

    # 3. Look for HTML report files (especially iLEAPP's primary DeviceInfo.html)
    if case.case_path:
        for html_file in case.case_path.rglob("*.html"):
            fname_low = html_file.name.lower()
            if any(h in fname_low for h in ["deviceinfo", "device", "system", "screen_output"]):
                try:
                    content = html_file.read_text(encoding="utf-8", errors="ignore")

                    # Match iLEAPP's standard DeviceInfo.html format: <li><b>Label:</b> Value ...
                    li_matches = re.findall(r"<li><b>([^:<]+):</b>\s*([^<]+)", content)
                    for k, v in li_matches:
                        clean_k = k.strip()
                        clean_v = v.strip()
                        if clean_k and clean_v and clean_k not in raw_meta:
                            raw_meta[clean_k] = clean_v
                            raw_src[clean_k] = {"source_file": case._rel(html_file)}

                    # Match standard HTML table rows: <tr><td>Key</td><td>Value</td></tr>
                    table_matches = re.findall(
                        r"<tr>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>",
                        content,
                        re.DOTALL | re.IGNORECASE,
                    )
                    for k, v in table_matches:
                        clean_k = re.sub(r"<[^>]+>", "", k).strip()
                        clean_v = re.sub(r"<[^>]+>", "", v).strip()
                        if clean_k and clean_v and clean_k not in raw_meta:
                            raw_meta[clean_k] = clean_v
                            raw_src[clean_k] = {"source_file": case._rel(html_file)}
                except Exception as e:
                    logger.warning("Error inspecting HTML %s: %s", html_file, e)

    # Helper to find key case-insensitively and tolerating spaces/underscores
    sources: dict[str, dict[str, Any]] = {}

    def find_val(field: str, *keys: str) -> str | None:
        """Value for an output field; records which source row it was taken from."""
        norm_targets = [re.sub(r"[\s_-]+", "", k.lower()) for k in keys]
        for exact in (True, False):
            for raw_k, v in raw_meta.items():
                if not v:
                    continue
                raw_norm = re.sub(r"[\s_-]+", "", str(raw_k).lower())
                if raw_norm in norm_targets if exact else any(t in raw_norm for t in norm_targets):
                    sources[field] = {"matched_key": raw_k, **raw_src.get(raw_k, {})}
                    return v
        return None

    return DeviceInfo(
        device_name=find_val(
            "device_name", "Device Name", "DeviceName", "Product Name", "Host Name"
        ),
        ios_version=find_val(
            "ios_version",
            "iOS Version",
            "Product Version",
            "OS Version",
            "Build Version",
            "Firmware",
            "ProductBuildVersion",
        ),
        product_type=find_val(
            "product_type", "Product Type", "ProductType", "Model Number", "Model", "Device Model"
        ),
        serial_number=find_val("serial_number", "Serial Number", "SerialNumber", "Hardware Serial"),
        imei=find_val("imei", "IMEI", "IMEI Number", "International Mobile Equipment Identity"),
        phone_number=find_val(
            "phone_number", "Phone Number", "PhoneNumber", "MSISDN", "Line1 Number"
        ),
        timezone=find_val(
            "timezone", "Time Zone", "Timezone", "Device Timezone", "Active Time Zone"
        ),
        extraction_type=find_val(
            "extraction_type",
            "Extraction Type",
            "Source Type",
            "Extraction Format",
            "Source",
            "Acquisition",
        ),
        extraction_date=find_val(
            "extraction_date",
            "Extraction Date",
            "Extraction Time",
            "Date Processed",
            "Processing Date",
            "Generated On",
        ),
        sources=sources,
    )
