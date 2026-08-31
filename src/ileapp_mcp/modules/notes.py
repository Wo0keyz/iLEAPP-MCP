import logging
import re
from collections.abc import Generator
from pathlib import Path
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import NoteRecord, PaginatedResult

logger = logging.getLogger(__name__)


def _find_field(keys: list[str], raw: dict[str, Any]) -> Any | None:
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
        if any(target in raw_norm for target in norm_targets):
            return raw_v
    return None


def get_notes_and_memos(
    case: CaseManager,
    keyword: str | None = None,
    note_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[NoteRecord]:
    if not case.is_loaded:
        raise ValueError("No case loaded.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)
    results: list[NoteRecord] = []
    global_total_count = 0

    all_files = list(case.get_all_tsv_files()) + list(case.get_all_sqlite_dbs())
    for file_path in all_files:
        stem = file_path.stem
        name_low = stem.lower()
        if any(x in name_low for x in ["note", "memo", "reminder", "calendar", "event"]):
            if note_type and note_type.lower() not in name_low:
                continue

            try:
                if file_path.suffix.lower() in [".tsv", ".csv"]:
                    rows_iterator = case.iter_tsv_rows(file_path)
                else:
                    try:
                        conn = case.get_sqlite_connection(file_path)
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        )
                        tables = [r[0] for r in cursor.fetchall()]
                    except Exception:
                        tables = [stem]

                    def yield_from_tables(
                        fp: Path, tbls: list[str]
                    ) -> Generator[dict[str, Any], None, None]:
                        for tbl in tbls:
                            yield from case.iter_sqlite_rows(fp, f"SELECT * FROM `{tbl}`")

                    rows_iterator = yield_from_tables(file_path, tables)

                if rows_iterator:
                    for row in rows_iterator:
                        ts = _find_field(["timestamp", "date", "creation", "lastmodified"], row)
                        if ts:
                            ts = str(ts)
                            if start_date and ts < start_date:
                                continue
                            if end_date and ts > end_date:
                                continue

                        title = _find_field(["title", "subject", "name", "heading"], row)
                        content = _find_field(
                            ["content", "body", "text", "snippet", "summary", "data"], row
                        )
                        fpath = _find_field(["path", "file", "attachment", "uri"], row)

                        if keyword:
                            search_space = f"{title or ''} {content or ''}".lower()
                            if keyword.lower() not in search_space:
                                continue

                        ntype = "Notes"
                        if "memo" in name_low:
                            ntype = "Voice Memo"
                        elif "reminder" in name_low:
                            ntype = "Reminder"
                        elif "calendar" in name_low or "event" in name_low:
                            ntype = "Calendar"

                        if offset <= global_total_count < offset + limit:
                            results.append(
                                NoteRecord(
                                    timestamp=str(ts) if ts else None,
                                    note_type=ntype,
                                    title=str(title) if title else None,
                                    content=str(content) if content else None,
                                    file_path=str(fpath) if fpath else None,
                                    raw_data=row,
                                )
                            )
                        global_total_count += 1

            except Exception as e:
                logger.warning(f"Error querying notes artifact {stem}: {e}")

    total_count = global_total_count
    paginated_items = results
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None

    return PaginatedResult[NoteRecord](
        items=paginated_items,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
