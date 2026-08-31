import logging

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
        for web in web_res.items:
            if web.timestamp:
                if web.search_term:
                    summary = f'{web.browser} Search: "{web.search_term}"'
                elif web.title:
                    summary = f"{web.browser} Visited: {web.title} ({web.url})"
                else:
                    summary = f"{web.browser} Visited: {web.url}"

                events.append(
                    TimelineEvent(
                        timestamp=web.timestamp,
                        category="web",
                        source_artifact=f"{web.browser}_{web.record_type}",
                        summary=summary.strip(),
                        details={
                            "url": web.url,
                            "title": web.title,
                            "search_term": web.search_term,
                            "record_type": web.record_type,
                        },
                    )
                )

    # 4. Locations
    if include_all or "locations" in cats or "geo" in cats:
        loc_res = get_location_history(
            case, start_date=start_date, end_date=end_date, limit=1000, offset=0
        )
        for loc in loc_res.items:
            if loc.timestamp:
                coords = (
                    f"[{loc.latitude:.5f}, {loc.longitude:.5f}]"
                    if loc.latitude and loc.longitude
                    else ""
                )
                desc_txt = f" - {loc.description}" if loc.description else ""
                summary = f"{loc.source_type} Position {coords}{desc_txt}"

                events.append(
                    TimelineEvent(
                        timestamp=loc.timestamp,
                        category="locations",
                        source_artifact=loc.source_type,
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
                # Apply date filter on install date if present
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
