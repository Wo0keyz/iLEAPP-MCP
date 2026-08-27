import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import PaginatedResult, WebRecord

logger = logging.getLogger(__name__)


def _extract_search_term_from_url(url: str) -> str | None:
    """Extract search queries from Google, Bing, DuckDuckGo, Yahoo, etc. URLs."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if any(
            engine in netloc
            for engine in ["google.", "bing.", "duckduckgo.", "yahoo.", "ecosia.", "qwant."]
        ):
            qs = parse_qs(parsed.query)
            for param in ["q", "query", "p", "text"]:
                if param in qs and qs[param]:
                    return qs[param][0]
    except Exception:
        pass
    return None


def _normalize_web_record(
    raw: dict[str, Any], default_browser: str = "Safari", default_type: str = "history"
) -> WebRecord:
    """Normalize fields across Safari, Chrome, and other browser artifacts."""
    # Find timestamp
    ts = None
    for k in [
        "Visit Time",
        "Date",
        "Timestamp",
        "Last Visited",
        "Created Date",
        "Time",
        "Date/Time",
    ]:
        for raw_k, raw_v in raw.items():
            if k.lower() == raw_k.lower() and raw_v:
                ts = str(raw_v).strip()
                break
        if ts:
            break

    # Find URL
    url = None
    for k in ["URL", "Visited URL", "Link", "Address", "Location"]:
        for raw_k, raw_v in raw.items():
            if k.lower() == raw_k.lower() and raw_v:
                url = str(raw_v).strip()
                break
        if url:
            break

    # Find title
    title = None
    for k in ["Title", "Page Title", "Name", "Bookmark Title"]:
        for raw_k, raw_v in raw.items():
            if k.lower() == raw_k.lower() and raw_v:
                title = str(raw_v).strip()
                break
        if title:
            break

    # Find visit count
    visit_count: int | None = None
    for k in ["Visit Count", "Visits", "Count"]:
        for raw_k, raw_v in raw.items():
            if k.lower() == raw_k.lower() and raw_v:
                try:
                    visit_count = int(str(raw_v).strip())
                    break
                except ValueError:
                    pass
        if visit_count is not None:
            break

    # Find search term directly or parse from URL
    search_term = None
    for k in ["Search Term", "Search Query", "Search", "Query"]:
        for raw_k, raw_v in raw.items():
            if k.lower() == raw_k.lower() and raw_v:
                val = str(raw_v).strip()
                if val and val != "None":
                    search_term = val
                    break
        if search_term:
            break

    if not search_term and url:
        search_term = _extract_search_term_from_url(url)

    # Determine record type
    rec_type = default_type
    if search_term and rec_type == "history":
        rec_type = "search"

    return WebRecord(
        timestamp=ts,
        browser=default_browser,
        record_type=rec_type,
        url=url,
        title=title,
        visit_count=visit_count,
        search_term=search_term,
        raw_data=raw,
    )


def get_web_activity(
    case: CaseManager,
    domain: str | None = None,
    search_query: str | None = None,
    activity_type: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[WebRecord]:
    """Retrieve and filter web browsing history, bookmarks, downloads, and search queries."""
    if not case.is_loaded:
        raise ValueError("No case loaded. Please call load_case first.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)

    all_records: list[WebRecord] = []
    target_hints = ["safari", "chrome", "browser", "web_history", "bookmarks", "downloads", "web"]

    # 1. Search SQLite databases
    for db_path in case.get_all_sqlite_dbs():
        stem = db_path.stem.lower()
        if any(t in stem for t in target_hints):
            browser = "Chrome" if "chrome" in stem else "Safari"
            rec_type = "history"
            if "bookmark" in stem:
                rec_type = "bookmark"
            elif "download" in stem:
                rec_type = "download"
            elif "tab" in stem:
                rec_type = "tab"

            try:
                conn = case.get_sqlite_connection(db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                tables = [r[0] for r in cursor.fetchall()]
                for table in tables:
                    cursor.execute(f"SELECT * FROM `{table}`")
                    cols = [d[0] for d in cursor.description] if cursor.description else []
                    rows = cursor.fetchall()
                    for r in rows:
                        row_dict = dict(zip(cols, r, strict=False))
                        all_records.append(
                            _normalize_web_record(
                                row_dict, default_browser=browser, default_type=rec_type
                            )
                        )
            except Exception as e:
                logger.debug("Error reading web activity from SQLite %s: %s", db_path, e)

    # 2. Search TSV files
    for tsv_path in case.get_all_tsv_files():
        stem = tsv_path.stem.lower()
        if any(t in stem for t in target_hints):
            browser = "Chrome" if "chrome" in stem else "Safari"
            rec_type = "history"
            if "bookmark" in stem:
                rec_type = "bookmark"
            elif "download" in stem:
                rec_type = "download"
            elif "tab" in stem:
                rec_type = "tab"
            elif "search" in stem:
                rec_type = "search"

            rows = case.read_tsv_records(tsv_path)
            for r in rows:
                all_records.append(
                    _normalize_web_record(r, default_browser=browser, default_type=rec_type)
                )

    # De-duplicate
    seen = set()
    deduped: list[WebRecord] = []
    for w in all_records:
        key = (w.timestamp or "", w.url or "", w.title or "", w.record_type)
        if key not in seen:
            seen.add(key)
            deduped.append(w)

    # Apply filters
    filtered: list[WebRecord] = []
    for w in deduped:
        if activity_type.lower() != "all" and activity_type.lower() not in w.record_type.lower():
            continue

        if domain:
            dom = domain.lower()
            url_match = w.url and dom in w.url.lower()
            title_match = w.title and dom in w.title.lower()
            if not (url_match or title_match):
                continue

        if search_query:
            sq = search_query.lower()
            st_match = w.search_term and sq in w.search_term.lower()
            url_match = w.url and sq in w.url.lower()
            title_match = w.title and sq in w.title.lower()
            if not (st_match or url_match or title_match):
                continue

        if start_date and w.timestamp and w.timestamp < start_date:
            continue

        if end_date and w.timestamp and w.timestamp > end_date:
            continue

        filtered.append(w)

    filtered.sort(key=lambda x: x.timestamp or "")

    total_count = len(filtered)
    page = filtered[offset : offset + limit]
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None

    return PaginatedResult[WebRecord](
        items=page,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
