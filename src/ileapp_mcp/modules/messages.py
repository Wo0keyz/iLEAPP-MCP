import logging
import re
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import MessageRecord, PaginatedResult

logger = logging.getLogger(__name__)


def _find_field(
    keys: list[str], raw: dict[str, Any], exclude_suffixes: tuple[str, ...] = ()
) -> Any | None:
    """Find a value in raw dictionary matching any key in keys (case- and delimiter-insensitive)."""
    norm_targets = [re.sub(r"[\s_-]+", "", k.lower()) for k in keys]

    # Pass 1: Exact normalized match
    for raw_k, raw_v in raw.items():
        if raw_v is None or raw_v == "":
            continue
        raw_norm = re.sub(r"[\s_-]+", "", str(raw_k).lower())
        if raw_norm in norm_targets:
            return raw_v

    # Pass 2: Substring match with exclusion of conflicting suffixes
    for raw_k, raw_v in raw.items():
        if raw_v is None or raw_v == "":
            continue
        raw_norm = re.sub(r"[\s_-]+", "", str(raw_k).lower())
        if any(raw_norm.endswith(ex) for ex in exclude_suffixes):
            continue
        for nt in norm_targets:
            if len(nt) >= 4 and (nt in raw_norm or raw_norm in nt):
                return raw_v
    return None


def _normalize_message_record(raw: dict[str, Any], default_app: str = "iMessage") -> MessageRecord:
    """Normalize fields across different iLEAPP message plugins and DB schemas."""
    ts = _find_field(
        ["Message Date", "Date", "Timestamp", "Delivered Date", "Read Date", "Time"],
        raw,
        exclude_suffixes=("id", "text", "body", "sender", "recipient"),
    )
    ts_str = str(ts).strip() if ts else None

    text = _find_field(
        ["Message Text", "Text Message", "Message Content", "Text", "Body", "Content", "Message"],
        raw,
        exclude_suffixes=(
            "date",
            "time",
            "timestamp",
            "id",
            "type",
            "direction",
            "status",
            "sender",
            "recipient",
            "service",
        ),
    )
    text_str = str(text).strip() if text else None

    sender = _find_field(
        ["Sender ID", "Sender Number", "Chat Sender", "Sender", "From", "Author"],
        raw,
        exclude_suffixes=("date", "time", "text", "body", "recipient"),
    )
    sender_str = str(sender).strip() if sender else None

    recipient = _find_field(
        ["Recipient ID", "Recipient Number", "Group ID", "Destination", "Recipient", "To"],
        raw,
        exclude_suffixes=("date", "time", "text", "body", "sender"),
    )
    recipient_str = str(recipient).strip() if recipient else None

    direction_raw = _find_field(
        ["Message Direction", "Is From Me", "Direction", "Type", "Status"],
        raw,
        exclude_suffixes=("date", "time", "text", "body"),
    )
    direction = None
    if direction_raw is not None:
        v_str = str(direction_raw).strip()
        if v_str == "1" or v_str.lower() in {"from me", "outgoing", "sent"}:
            direction = "Outgoing"
        elif v_str == "0" or v_str.lower() in {"incoming", "received"}:
            direction = "Incoming"
        else:
            direction = v_str

    app_raw = _find_field(
        ["Service", "App", "Source", "Application", "Protocol"],
        raw,
        exclude_suffixes=("date", "time", "text", "body"),
    )
    app = str(app_raw).strip() if app_raw else default_app

    attachment_raw = _find_field(
        ["Attachment", "Attachments", "Filename", "File Path", "Media"],
        raw,
        exclude_suffixes=("date", "time", "text", "body"),
    )
    attachments: list[str] = []
    if attachment_raw:
        val = str(attachment_raw).strip()
        if val and val.lower() not in {"none", "n/a", "null"}:
            attachments.append(val)

    return MessageRecord(
        timestamp=ts_str,
        app=app,
        sender=sender_str,
        recipient=recipient_str,
        message_text=text_str,
        direction=direction,
        attachment_count=len(attachments),
        attachment_paths=attachments,
        raw_data=raw,
    )


def get_messages(
    case: CaseManager,
    sender: str | None = None,
    recipient: str | None = None,
    keyword: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    app: str = "all",
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[MessageRecord]:
    """Retrieve and filter messages across SMS, iMessage, WhatsApp, Telegram, and other messaging artifacts."""
    if not case.is_loaded:
        raise ValueError("No case loaded. Please call load_case first.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)

    all_records: list[MessageRecord] = []
    target_dbs = ["sms", "message", "imessage", "whatsapp", "telegram", "signal", "chat", "viber"]

    # 1. Search SQLite databases
    for db_path in case.get_all_sqlite_dbs():
        stem = db_path.stem.lower()
        if any(t in stem for t in target_dbs):
            try:
                conn = case.get_sqlite_connection(db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                tables = [r[0] for r in cursor.fetchall()]
                for table in tables:
                    db_app = "iMessage"
                    if "whatsapp" in stem or "whatsapp" in table.lower():
                        db_app = "WhatsApp"
                    elif "telegram" in stem:
                        db_app = "Telegram"
                    elif "signal" in stem:
                        db_app = "Signal"
                    elif "sms" in stem:
                        db_app = "SMS/iMessage"

                    cursor.execute(f"SELECT * FROM `{table}`")
                    cols = [d[0] for d in cursor.description] if cursor.description else []
                    rows = cursor.fetchall()
                    for r in rows:
                        row_dict = dict(zip(cols, r, strict=False))
                        all_records.append(_normalize_message_record(row_dict, default_app=db_app))
            except Exception as e:
                logger.debug("Error querying SQLite messages from %s: %s", db_path, e)

    # 2. Search TSV/CSV files
    for tsv_path in case.get_all_tsv_files():
        stem = tsv_path.stem.lower()
        if any(t in stem for t in target_dbs):
            default_app = "iMessage"
            if "whatsapp" in stem:
                default_app = "WhatsApp"
            elif "telegram" in stem:
                default_app = "Telegram"
            elif "sms" in stem:
                default_app = "SMS/iMessage"

            tsv_rows = case.read_tsv_records(tsv_path)
            for row in tsv_rows:
                all_records.append(_normalize_message_record(row, default_app=default_app))

    # De-duplicate
    seen = set()
    deduped_records: list[MessageRecord] = []
    for m in all_records:
        key = (m.timestamp or "", m.sender or "", m.message_text or "", m.app)
        if key not in seen:
            seen.add(key)
            deduped_records.append(m)

    # Apply filters
    filtered: list[MessageRecord] = []
    for msg in deduped_records:
        if app.lower() != "all" and app.lower() not in msg.app.lower():
            continue

        if sender and (not msg.sender or sender.lower() not in msg.sender.lower()):
            continue

        if recipient and (not msg.recipient or recipient.lower() not in msg.recipient.lower()):
            continue

        if keyword:
            kw = keyword.lower()
            text_match = msg.message_text and kw in msg.message_text.lower()
            sender_match = msg.sender and kw in msg.sender.lower()
            recip_match = msg.recipient and kw in msg.recipient.lower()
            if not (text_match or sender_match or recip_match):
                continue

        if start_date and msg.timestamp and msg.timestamp < start_date:
            continue

        if end_date and msg.timestamp and msg.timestamp > end_date:
            continue

        filtered.append(msg)

    filtered.sort(key=lambda x: x.timestamp or "")

    total_count = len(filtered)
    page = filtered[offset : offset + limit]
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None

    return PaginatedResult[MessageRecord](
        items=page,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
