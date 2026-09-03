import contextlib
import logging
import math
import re
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import LocationRecord, PaginatedResult

logger = logging.getLogger(__name__)


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on the Earth in kilometers."""
    r = 6371.0  # Earth's radius in kilometers
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


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


def _normalize_location_record(raw: dict[str, Any], default_source: str = "GPS") -> LocationRecord:
    """Normalize fields across different location artifacts in iLEAPP."""
    ts = _find_field(
        ["Timestamp", "Date", "Date/Time", "Visit Entry", "Entry Date", "Time", "Visit Exit"], raw
    )
    ts_str = str(ts).strip() if ts else None

    # Find latitude & longitude
    lat_raw = _find_field(["Latitude", "Lat", "Location Latitude", "Geopoint Latitude"], raw)
    lat: float | None = None
    if lat_raw is not None:
        with contextlib.suppress(ValueError):
            parsed = float(str(lat_raw).strip())
            if not math.isnan(parsed) and not math.isinf(parsed) and -90.0 <= parsed <= 90.0:
                lat = parsed

    lon_raw = _find_field(
        ["Longitude", "Lon", "Long", "Location Longitude", "Geopoint Longitude"], raw
    )
    lon: float | None = None
    if lon_raw is not None:
        with contextlib.suppress(ValueError):
            parsed = float(str(lon_raw).strip())
            if not math.isnan(parsed) and not math.isinf(parsed) and -180.0 <= parsed <= 180.0:
                lon = parsed

    # If coordinates formatted as combined string
    if lat is None and lon is None:
        coords_raw = _find_field(["Coordinates", "Location", "Geo", "Position"], raw)
        if coords_raw:
            m = re.match(r"([-+]?\d*\.?\d+)[,\s]+([-+]?\d*\.?\d+)", str(coords_raw).strip())
            if m:
                with contextlib.suppress(ValueError):
                    p_lat = float(m.group(1))
                    p_lon = float(m.group(2))
                    if -90.0 <= p_lat <= 90.0 and -180.0 <= p_lon <= 180.0:
                        lat = p_lat
                        lon = p_lon

    alt_raw = _find_field(["Altitude", "Alt"], raw)
    alt: float | None = None
    if alt_raw is not None:
        with contextlib.suppress(ValueError):
            parsed = float(str(alt_raw).strip())
            if not math.isnan(parsed) and not math.isinf(parsed):
                alt = parsed

    acc_raw = _find_field(
        ["Horizontal Accuracy", "Accuracy", "Confidence", "HorizontalAccuracy"], raw
    )
    acc: float | None = None
    if acc_raw is not None:
        with contextlib.suppress(ValueError):
            parsed = float(str(acc_raw).strip())
            if not math.isnan(parsed) and not math.isinf(parsed):
                acc = parsed

    source_raw = _find_field(["Source", "Provider", "Origin", "Artifact"], raw)
    source = str(source_raw).strip() if source_raw else default_source

    desc_raw = _find_field(
        ["Description", "Address", "Name", "Place Name", "Label", "City", "Location Name"], raw
    )
    desc = (
        str(desc_raw).strip()
        if desc_raw and str(desc_raw).lower() not in {"none", "null"}
        else None
    )

    return LocationRecord(
        timestamp=ts_str,
        latitude=lat,
        longitude=lon,
        altitude=alt,
        horizontal_accuracy=acc,
        source_type=source,
        description=desc,
        raw_data=raw,
    )


def get_location_history(
    case: CaseManager,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    source_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[LocationRecord]:
    """Retrieve and filter geo-locations, significant places, Routine caches, and Apple Maps records."""
    if not case.is_loaded:
        raise ValueError("No case loaded. Please call load_case first.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)

    target_hints = [
        "location",
        "routine",
        "significant",
        "apple_maps",
        "cell_tower",
        "wifi",
        "geo",
        "parked_car",
        "gps",
        "consolidated",
        "cache_sqlite",
    ]

    seen = set()
    filtered: list[LocationRecord] = []
    total_count = 0

    def process_row(r_dict: dict[str, Any], default_source: str) -> None:
        nonlocal total_count
        loc = _normalize_location_record(r_dict, default_source=default_source)

        if loc.latitude is None and loc.longitude is None and not loc.description:
            return

        if source_type and (
            not loc.source_type or source_type.lower() not in loc.source_type.lower()
        ):
            return

        if start_date and loc.timestamp and loc.timestamp < start_date:
            return

        if end_date and loc.timestamp and loc.timestamp > end_date:
            return

        if latitude is not None and longitude is not None and radius_km is not None:
            if loc.latitude is None or loc.longitude is None:
                return
            dist = haversine_distance_km(latitude, longitude, loc.latitude, loc.longitude)
            if dist > radius_km:
                return

        key = (loc.timestamp or "", loc.latitude, loc.longitude, loc.source_type)
        if key not in seen:
            seen.add(key)
            total_count += 1
            if len(filtered) < offset + limit:
                filtered.append(loc)

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
                source_name = "Significant Locations" if "routine" in stem else "LocationD"
                for table in tables:
                    for row_dict in case.iter_sqlite_rows(db_path, f"SELECT * FROM `{table}`"):
                        process_row(row_dict, default_source=source_name)
            except Exception as e:
                logger.debug("Error reading locations from SQLite %s: %s", db_path, e)

    # 2. Search TSV files
    for tsv_path in case.get_all_tsv_files():
        stem = tsv_path.stem.lower()
        if any(t in stem for t in target_hints):
            source_name = "Apple Maps" if "map" in stem else "Location TSV"
            try:
                for row_dict in case.iter_tsv_rows(tsv_path):
                    process_row(row_dict, default_source=source_name)
            except Exception as e:
                logger.debug("Error reading locations from TSV %s: %s", tsv_path, e)

    filtered.sort(key=lambda x: x.timestamp or "")

    page = filtered[offset : offset + limit]
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None

    return PaginatedResult[LocationRecord](
        items=page,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
