import logging
import re

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import DeviceInfo

logger = logging.getLogger(__name__)


def get_device_info(case: CaseManager) -> DeviceInfo:
    """Extract hardware, iOS version, serial, and case metadata from the iLEAPP report."""
    if not case.is_loaded or not case.case_path:
        raise ValueError("No iLEAPP case is currently loaded. Use load_case first.")

    raw_meta: dict[str, str] = {}

    # 1. Look for TSV files related to device info / system info
    tsv_hints = [
        "device_information",
        "system_info",
        "device_info",
        "build_info",
        "device_details",
        "sys_info",
    ]

    for hint in tsv_hints:
        tsv_path = case.get_tsv_path(hint)
        if tsv_path:
            records = case.read_tsv_records(tsv_path)
            for r in records:
                # Handle Key/Value structure or wide row structure
                if "Key" in r and "Value" in r:
                    raw_meta[r["Key"].strip()] = r["Value"].strip()
                elif "Property" in r and "Value" in r:
                    raw_meta[r["Property"].strip()] = r["Value"].strip()
                elif "Parameter" in r and "Value" in r:
                    raw_meta[r["Parameter"].strip()] = r["Value"].strip()
                else:
                    for k, v in r.items():
                        if k and v:
                            raw_meta[k.strip()] = str(v).strip()

    # 2. Check if a SQLite database contains system/device info table
    for db_path in case.get_all_sqlite_dbs():
        db_name = db_path.stem.lower()
        if any(h in db_name for h in ["device", "system", "report", "sys"]):
            try:
                conn = case.get_sqlite_connection(db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%info%' OR name LIKE '%device%' OR name LIKE '%system%')"
                )
                tables = [row[0] for row in cursor.fetchall()]
                for tbl in tables:
                    cursor.execute(f"SELECT * FROM `{tbl}` LIMIT 100")
                    rows = cursor.fetchall()
                    cols = [d[0] for d in cursor.description] if cursor.description else []
                    for row in rows:
                        row_dict = dict(zip(cols, row, strict=False))
                        if "Key" in row_dict and "Value" in row_dict:
                            raw_meta[str(row_dict["Key"]).strip()] = str(row_dict["Value"]).strip()
                        elif "Property" in row_dict and "Value" in row_dict:
                            raw_meta[str(row_dict["Property"]).strip()] = str(
                                row_dict["Value"]
                            ).strip()
                        else:
                            for k, v in row_dict.items():
                                if k and v is not None and str(k) not in raw_meta:
                                    raw_meta[str(k).strip()] = str(v).strip()
            except Exception as e:
                logger.debug("Error inspecting SQLite DB %s for device info: %s", db_path, e)

    # 3. Look for HTML report files if metadata is still sparse
    if len(raw_meta) < 2 and case.case_path:
        for html_file in case.case_path.rglob("*.html"):
            if any(h in html_file.name.lower() for h in ["device", "system", "index"]):
                try:
                    content = html_file.read_text(encoding="utf-8", errors="ignore")
                    # Match standard table rows: <td>Key</td><td>Value</td>
                    matches = re.findall(
                        r"<tr>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>",
                        content,
                        re.DOTALL | re.IGNORECASE,
                    )
                    for k, v in matches:
                        clean_k = re.sub(r"<[^>]+>", "", k).strip()
                        clean_v = re.sub(r"<[^>]+>", "", v).strip()
                        if clean_k and clean_v:
                            raw_meta[clean_k] = clean_v
                except Exception as e:
                    logger.debug("Error inspecting HTML %s: %s", html_file, e)

    # Helper to find key case-insensitively
    def find_val(*keys: str) -> str | None:
        for target in keys:
            for k, v in raw_meta.items():
                if (target.lower() == k.lower() or target.lower() in k.lower()) and v:
                    return v
        return None

    return DeviceInfo(
        device_name=find_val("Device Name", "DeviceName", "Product Name", "Host Name"),
        ios_version=find_val(
            "iOS Version", "Product Version", "OS Version", "Build Version", "Firmware"
        ),
        product_type=find_val(
            "Product Type", "ProductType", "Model Number", "Model", "Device Model"
        ),
        serial_number=find_val("Serial Number", "SerialNumber", "Hardware Serial"),
        imei=find_val("IMEI", "IMEI Number", "International Mobile Equipment Identity"),
        phone_number=find_val("Phone Number", "PhoneNumber", "MSISDN", "Line1 Number"),
        timezone=find_val("Time Zone", "Timezone", "Device Timezone", "Active Time Zone"),
        extraction_type=find_val(
            "Extraction Type", "Source Type", "Extraction Format", "Source", "Acquisition"
        ),
        extraction_date=find_val(
            "Extraction Date",
            "Extraction Time",
            "Date Processed",
            "Processing Date",
            "Generated On",
        ),
        raw_metadata=raw_meta,
    )
