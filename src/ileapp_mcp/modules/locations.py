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
    """Find a value in raw dictionary matching any key in keys (case- and delimiter-insensitive)."""
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
        for nt in norm_targets:
            if nt in raw_norm or raw_norm in nt:
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
            lat = float(str(lat_raw).strip())

    lon_raw = _find_field(
        ["Longitude", "Lon", "Long", "Location Longitude", "Geopoint Longitude"], raw
    )
    lon: float | None = None
    if lon_raw is not None:
        with contextlib.suppress(ValueError):
            lon = float(str(lon_raw).strip())

    # If coordinates formatted as combined string
    if lat is None and lon is None:
        coords_raw = _find_field(["Coordinates", "Location", "Geo", "Position"], raw)
        if coords_raw:
            m = re.match(r"([-+]?\d*\.?\d+)[,\s]+([-+]?\d*\.?\d+)", str(coords_raw).strip())
            if m:
                try:
                    lat = float(m.group(1))
                    lon = float(m.group(2))
                except ValueError:
                    pass

    alt_raw = _find_field(["Altitude", "Alt"], raw)
    alt: float | None = None
    if alt_raw is not None:
        with contextlib.suppress(ValueError):
            alt = float(str(alt_raw).strip())

    acc_raw = _find_field(
        ["Horizontal Accuracy", "Accuracy", "Confidence", "HorizontalAccuracy"], raw
    )
    acc: float | None = None
    if acc_raw is not None:
        with contextlib.suppress(ValueError):
            acc = float(str(acc_raw).strip())

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

    all_records: list[LocationRecord] = []
    target_hints = [
        "location",
        "routine",
        "significant",
        "apple_maps",
        "cell_tower",
        "wifi",
        "geo",
        "parked_car",
    ]

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
                    source_name = "Significant Locations" if "routine" in stem else "LocationD"
                    cursor.execute(f"SELECT * FROM `{table}`")
                    cols = [d[0] for d in cursor.description] if cursor.description else []
                    rows = cursor.fetchall()
                    for r in rows:
                        row_dict = dict(zip(cols, r, strict=False))
                        all_records.append(
                            _normalize_location_record(row_dict, default_source=source_name)
                        )
            except Exception as e:
                logger.debug("Error reading locations from SQLite %s: %s", db_path, e)

    # 2. Search TSV files
    for tsv_path in case.get_all_tsv_files():
        stem = tsv_path.stem.lower()
        if any(t in stem for t in target_hints):
            source_name = "Apple Maps" if "map" in stem else "Location TSV"
            rows = case.read_tsv_records(tsv_path)
            for r in rows:
                all_records.append(_normalize_location_record(r, default_source=source_name))

    # De-duplicate
    seen = set()
    deduped: list[LocationRecord] = []
    for loc in all_records:
        key = (loc.timestamp or "", loc.latitude, loc.longitude, loc.source_type)
        if key not in seen:
            seen.add(key)
            deduped.append(loc)

    # Apply filters
    filtered: list[LocationRecord] = []
    for loc in deduped:
        if source_type and (
            not loc.source_type or source_type.lower() not in loc.source_type.lower()
        ):
            continue

        if start_date and loc.timestamp and loc.timestamp < start_date:
            continue

        if end_date and loc.timestamp and loc.timestamp > end_date:
            continue

        if latitude is not None and longitude is not None and radius_km is not None:
            if loc.latitude is None or loc.longitude is None:
                continue
            dist = haversine_distance_km(latitude, longitude, loc.latitude, loc.longitude)
            if dist > radius_km:
                continue

        filtered.append(loc)

    filtered.sort(key=lambda x: x.timestamp or "")

    total_count = len(filtered)
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
