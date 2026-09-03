import json
import logging
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import PaginatedResult, TimelineEvent
from ileapp_mcp.modules.apps import get_installed_apps
from ileapp_mcp.modules.calls import get_call_history
from ileapp_mcp.modules.health import get_health_data
from ileapp_mcp.modules.locations import get_location_history
from ileapp_mcp.modules.messages import get_messages
from ileapp_mcp.modules.networks import get_network_connections
from ileapp_mcp.modules.notes import get_notes_and_memos
from ileapp_mcp.modules.photos import get_photos_metadata
from ileapp_mcp.modules.system_state import get_system_state
from ileapp_mcp.modules.web import get_web_activity

logger = logging.getLogger(__name__)


def _classify_activity(activity: str) -> str:
    """Classify an iLEAPP artifact activity name into a timeline category."""
    act_low = activity.lower()
    if any(
        k in act_low
        for k in ["message", "sms", "imessage", "chat", "whatsapp", "telegram", "signal"]
    ):
        return "messages"
    if any(k in act_low for k in ["call", "facetime", "voip"]):
        return "calls"
    if any(
        k in act_low
        for k in ["safari", "chrome", "firefox", "browser", "bookmark", "download", "web"]
    ):
        return "web"
    if any(k in act_low for k in ["location", "routine", "map", "gps", "significant"]):
        return "locations"
    if any(k in act_low for k in ["app", "bundle"]):
        return "apps"
    if any(k in act_low for k in ["health", "step", "heart", "workout", "sleep"]):
        return "health"
    if any(k in act_low for k in ["note", "memo", "reminder", "calendar", "event"]):
        return "notes"
    if any(k in act_low for k in ["photo", "media", "camera", "exif", "image", "video"]):
        return "photos"
    if any(k in act_low for k in ["wifi", "bluetooth", "cell", "network", "airdrop"]):
        return "networks"
    return "system"


def _create_summary_from_data(activity: str, _category: str, data_dict: dict[str, Any]) -> str:
    """Generate a brief human-readable summary from an iLEAPP timeline record."""
    # Look for common expressive fields
    for text_key in ["Message Text", "Text", "Body", "Content", "Search Term", "Query"]:
        if text_key in data_dict and data_dict[text_key]:
            val = str(data_dict[text_key]).strip()
            if len(val) > 70:
                val = val[:67] + "..."
            return f'{activity}: "{val}"'

    for name_key in ["Title", "Page Title", "Name", "SSID", "App Name", "Event"]:
        if name_key in data_dict and data_dict[name_key]:
            return f"{activity}: {data_dict[name_key]}"

    # Fallback to key items
    items = [f"{k}={v}" for k, v in list(data_dict.items())[:3] if v]
    return f"{activity}: {', '.join(items)}" if items else activity


def get_timeline(
    case: CaseManager,
    start_date: str | None = None,
    end_date: str | None = None,
    categories: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> PaginatedResult[TimelineEvent]:
    """Build a unified chronological timeline across communications, locations, web, and apps."""
    if not case.is_loaded:
        raise ValueError("No case loaded. Please call load_case first.")

    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    cats = [c.lower() for c in (categories or ["all"])]
    include_all = "all" in cats

    # --- FAST PATH: Check if iLEAPP's pre-compiled tl.db exists ---
    tldb_path = case.get_sqlite_path("tl.db") or case.get_sqlite_path("tl")
    if tldb_path:
        try:
            conn = case.get_sqlite_connection(tldb_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='data'")
            if cursor.fetchone():
                where_clauses = []
                params: list[Any] = []
                if start_date:
                    where_clauses.append("key >= ?")
                    params.append(start_date)
                if end_date:
                    where_clauses.append("key <= ?")
                    params.append(end_date)

                where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
                sql = f"SELECT key, activity, datalist FROM data{where_sql} ORDER BY key ASC"

                tl_events: list[TimelineEvent] = []
                total_matches = 0

                for row in case.iter_sqlite_rows(tldb_path, sql, tuple(params)):
                    act = str(row.get("activity", "")).strip()
                    cat = _classify_activity(act)
                    if not include_all and cat not in cats and "communications" not in cats:
                        continue
                    if "communications" in cats and cat not in ["messages", "calls"]:
                        continue

                    total_matches += 1
                    if len(tl_events) < offset + limit:
                        key_ts = str(row.get("key", "")).strip()
                        raw_data_str = str(row.get("datalist", "{}"))
                        try:
                            parsed_data = json.loads(raw_data_str)
                        except Exception:
                            parsed_data = {}

                        summary = _create_summary_from_data(act, cat, parsed_data)
                        tl_events.append(
                            TimelineEvent(
                                timestamp=key_ts,
                                category=cat,
                                source_artifact=act,
                                summary=summary,
                                details=parsed_data,
                            )
                        )

                if total_matches > 0:
                    page = tl_events[offset : offset + limit]
                    has_more = (offset + limit) < total_matches
                    return PaginatedResult[TimelineEvent](
                        items=page,
                        total_count=total_matches,
                        has_more=has_more,
                        limit=limit,
                        offset=offset,
                        next_offset=(offset + limit) if has_more else None,
                    )
        except Exception as e:
            logger.debug("Error using fast tl.db timeline, falling back to multi-module: %s", e)

    # --- FALLBACK PATH: Multi-module unified aggregation ---
    events: list[TimelineEvent] = []

    # 1. Messages
    if include_all or "messages" in cats or "communications" in cats:
        msg_res = get_messages(case, start_date=start_date, end_date=end_date, limit=1000, offset=0)
        for msg in msg_res.items:
            if msg.timestamp:
                direction_txt = f"[{msg.direction}] " if msg.direction else ""
                sender_txt = f"From: {msg.sender} " if msg.sender else ""
                recip_txt = f"To: {msg.recipient} " if msg.recipient else ""
                snippet = (
                    (msg.message_text[:60] + "...")
                    if msg.message_text and len(msg.message_text) > 60
                    else (msg.message_text or "No text")
                )
                summary = f'{msg.app} {direction_txt}{sender_txt}{recip_txt}: "{snippet}"'

                events.append(
                    TimelineEvent(
                        timestamp=msg.timestamp,
                        category="messages",
                        source_artifact=msg.app,
                        summary=summary.strip(),
                        details={
                            "sender": msg.sender,
                            "recipient": msg.recipient,
                            "message_text": msg.message_text,
                            "direction": msg.direction,
                            "attachments": msg.attachment_paths,
                        },
                    )
                )

    # 2. Calls
    if include_all or "calls" in cats or "communications" in cats:
        call_res = get_call_history(
            case, start_date=start_date, end_date=end_date, limit=1000, offset=0
        )
        for call in call_res.items:
            if call.timestamp:
                dur_txt = (
                    f" ({call.duration_seconds}s)" if call.duration_seconds is not None else ""
                )
                contact_txt = f" with {call.contact_name}" if call.contact_name else ""
                num_txt = f" ({call.phone_number})" if call.phone_number else ""
                summary = f"{call.app} {call.call_type or 'Call'}{contact_txt}{num_txt}{dur_txt}"

                events.append(
                    TimelineEvent(
                        timestamp=call.timestamp,
                        category="calls",
                        source_artifact=call.app,
                        summary=summary.strip(),
                        details={
                            "phone_number": call.phone_number,
                            "contact_name": call.contact_name,
                            "call_type": call.call_type,
                            "duration_seconds": call.duration_seconds,
                        },
                    )
                )

    # 3. Web Activity
    if include_all or "web" in cats or "browsing" in cats:
        web_res = get_web_activity(
            case, start_date=start_date, end_date=end_date, limit=1000, offset=0
        )
        for w in web_res.items:
            if w.timestamp:
                if w.record_type == "search":
                    summary = f'{w.browser} Search: "{w.search_term or w.title or w.url}"'
                elif w.record_type == "bookmark":
                    summary = f"{w.browser} Bookmark: {w.title or w.url}"
                else:
                    summary = f"{w.browser} Visit: {w.title or w.url}"

                events.append(
                    TimelineEvent(
                        timestamp=w.timestamp,
                        category="web",
                        source_artifact=f"{w.browser}_{w.record_type}",
                        summary=summary.strip(),
                        details={
                            "url": w.url,
                            "title": w.title,
                            "search_term": w.search_term,
                            "browser": w.browser,
                            "record_type": w.record_type,
                        },
                    )
                )

    # 4. Locations & Movements
    if include_all or "locations" in cats or "geo" in cats:
        loc_res = get_location_history(
            case, start_date=start_date, end_date=end_date, limit=1000, offset=0
        )
        for loc in loc_res.items:
            if loc.timestamp:
                coords_txt = (
                    f" ({loc.latitude:.4f}, {loc.longitude:.4f})"
                    if (loc.latitude is not None and loc.longitude is not None)
                    else ""
                )
                desc_txt = f": {loc.description}" if loc.description else ""
                summary = f"{loc.source_type} Position{coords_txt}{desc_txt}"

                events.append(
                    TimelineEvent(
                        timestamp=loc.timestamp,
                        category="locations",
                        source_artifact=loc.source_type.replace(" ", "_"),
                        summary=summary.strip(),
                        details={
                            "latitude": loc.latitude,
                            "longitude": loc.longitude,
                            "altitude": loc.altitude,
                            "accuracy": loc.horizontal_accuracy,
                            "description": loc.description,
                        },
                    )
                )

    # 5. Apps Installation / Updates
    if include_all or "apps" in cats:
        app_res = get_installed_apps(case, limit=500, offset=0)
        for app in app_res.items:
            if app.install_date:
                if start_date and app.install_date < start_date:
                    continue
                if end_date and app.install_date > end_date:
                    continue

                summary = f"App Installed/Updated: {app.app_name or app.bundle_id} (v{app.version or '?'})"
                events.append(
                    TimelineEvent(
                        timestamp=app.install_date,
                        category="apps",
                        source_artifact="Installed_Apps",
                        summary=summary.strip(),
                        details={
                            "app_name": app.app_name,
                            "bundle_id": app.bundle_id,
                            "version": app.version,
                            "permissions": app.permissions,
                        },
                    )
                )

    # 6. Health & Biometrics
    if include_all or "health" in cats:
        health_res = get_health_data(case, limit=1000, offset=0)
        for h in health_res.items:
            if h.timestamp:
                summary = f"Health: {h.metric_type} = {h.value} {h.unit or ''}"
                events.append(
                    TimelineEvent(
                        timestamp=h.timestamp,
                        category="health",
                        source_artifact="HealthData",
                        summary=summary.strip(),
                        details={"metric_type": h.metric_type, "value": h.value, "unit": h.unit},
                    )
                )

    # 7. Notes & Memos
    if include_all or "notes" in cats or "memos" in cats:
        notes_res = get_notes_and_memos(case, limit=1000, offset=0)
        for n in notes_res.items:
            if n.timestamp:
                summary = f"{n.note_type}: {n.title or n.content or 'No Title'}"
                events.append(
                    TimelineEvent(
                        timestamp=n.timestamp,
                        category="notes",
                        source_artifact=n.note_type.replace(" ", ""),
                        summary=summary[:150].strip(),
                        details={"title": n.title, "content": n.content, "file_path": n.file_path},
                    )
                )

    # 8. Photos & Media
    if include_all or "photos" in cats or "media" in cats:
        photos_res = get_photos_metadata(case, limit=1000, offset=0)
        for p in photos_res.items:
            if p.timestamp:
                del_str = " (Deleted)" if p.is_deleted else ""
                summary = f"{p.media_type}{del_str}: {p.file_name or 'Unknown'} [Album: {p.album_name or 'None'}]"
                events.append(
                    TimelineEvent(
                        timestamp=p.timestamp,
                        category="photos",
                        source_artifact="PhotosDB",
                        summary=summary.strip(),
                        details={
                            "file_name": p.file_name,
                            "latitude": p.latitude,
                            "longitude": p.longitude,
                            "camera": p.camera_model,
                            "deleted": p.is_deleted,
                            "file_path": p.file_path,
                        },
                    )
                )

    # 9. Network Connections
    if include_all or "networks" in cats or "wireless" in cats:
        net_res = get_network_connections(case, limit=1000, offset=0)
        for net in net_res.items:
            if net.timestamp:
                summary = (
                    f"{net.connection_type} Connection: {net.ssid_or_name or net.bssid_or_mac}"
                )
                events.append(
                    TimelineEvent(
                        timestamp=net.timestamp,
                        category="networks",
                        source_artifact=net.connection_type.replace(" ", ""),
                        summary=summary.strip(),
                        details={
                            "ssid_or_name": net.ssid_or_name,
                            "bssid_or_mac": net.bssid_or_mac,
                            "duration": net.duration_seconds,
                        },
                    )
                )

    # 10. System State
    if include_all or "system" in cats:
        sys_res = get_system_state(case, limit=1000, offset=0)
        for s in sys_res.items:
            if s.timestamp:
                summary = f"System Event: {s.event_type} - {s.value}"
                events.append(
                    TimelineEvent(
                        timestamp=s.timestamp,
                        category="system",
                        source_artifact="SystemState",
                        summary=summary.strip(),
                        details={"event_type": s.event_type, "value": s.value},
                    )
                )

    # Sort all events strictly by timestamp ascending
    events.sort(key=lambda x: x.timestamp)

    total_count = len(events)
    page = events[offset : offset + limit]
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None

    return PaginatedResult[TimelineEvent](
        items=page,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
