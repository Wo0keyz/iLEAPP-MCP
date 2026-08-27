import logging

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import PaginatedResult, TimelineEvent
from ileapp_mcp.modules.apps import get_installed_apps
from ileapp_mcp.modules.calls import get_call_history
from ileapp_mcp.modules.locations import get_location_history
from ileapp_mcp.modules.messages import get_messages
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
