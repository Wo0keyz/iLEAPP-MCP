import contextlib
import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import PaginatedResult, WebRecord

logger = logging.getLogger(__name__)


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
    """Normalize fields across Safari, Chrome, Firefox, DuckDuckGo, and Tor artifacts."""
    ts_raw = _find_field(
        ["Visit Time", "Date", "Timestamp", "Last Visited", "Created Date", "Time", "Date/Time"],
        raw,
    )
    ts = str(ts_raw).strip() if ts_raw else None

    url_raw = _find_field(["URL", "Visited URL", "Link", "Address", "Location", "Page URL"], raw)
    url = str(url_raw).strip() if url_raw else None

    title_raw = _find_field(["Title", "Page Title", "Name", "Bookmark Title", "Topic"], raw)
    title = str(title_raw).strip() if title_raw else None

    vc_raw = _find_field(["Visit Count", "Visits", "Count"], raw)
    visit_count: int | None = None
    if vc_raw is not None:
        with contextlib.suppress(ValueError):
            visit_count = int(str(vc_raw).strip())

    search_raw = _find_field(["Search Term", "Search Query", "Search", "Query"], raw)
    search_term = (
        str(search_raw).strip() if search_raw and str(search_raw).lower() != "none" else None
    )
    if not search_term and url:
        search_term = _extract_search_term_from_url(url)

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

    target_hints = [
        "safari",
        "chrome",
        "firefox",
        "duckduckgo",
        "onion",
        "ornet",
        "browser",
        "web_history",
        "bookmarks",
        "downloads",
        "web",
        "search",
        "tab",
    ]

    seen = set()
    filtered: list[WebRecord] = []
    total_count = 0

    def process_row(r_dict: dict[str, Any], default_browser: str, default_type: str) -> None:
        nonlocal total_count
        rec = _normalize_web_record(
            r_dict, default_browser=default_browser, default_type=default_type
        )

        if not rec.url and not rec.title and not rec.search_term:
            return

        if activity_type.lower() != "all" and activity_type.lower() not in rec.record_type.lower():
            return

        if domain:
            dom_low = domain.lower()
            url_match = rec.url and dom_low in rec.url.lower()
            title_match = rec.title and dom_low in rec.title.lower()
            if not (url_match or title_match):
                return

        if search_query:
            sq_low = search_query.lower()
            st_match = rec.search_term and sq_low in rec.search_term.lower()
            url_match = rec.url and sq_low in rec.url.lower()
            title_match = rec.title and sq_low in rec.title.lower()
            if not (st_match or url_match or title_match):
                return

        if start_date and rec.timestamp and rec.timestamp < start_date:
            return

        if end_date and rec.timestamp and rec.timestamp > end_date:
            return

        key = (rec.timestamp or "", rec.browser, rec.url or "", rec.record_type)
        if key not in seen:
            seen.add(key)
            total_count += 1
            if len(filtered) < offset + limit:
                filtered.append(rec)

    # 1. Search SQLite databases
    for db_path in case.get_all_sqlite_dbs():
        stem = db_path.stem.lower()
        if any(t in stem for t in target_hints):
            browser = "Safari"
            if "chrome" in stem:
                browser = "Chrome"
            elif "firefox" in stem:
                browser = "Firefox"
            elif "duckduckgo" in stem:
                browser = "DuckDuckGo"
            elif "onion" in stem or "ornet" in stem:
                browser = "Tor/Onion Browser"

            rec_type = "history"
            if "bookmark" in stem:
                rec_type = "bookmark"
            elif "download" in stem:
                rec_type = "download"
            elif "tab" in stem:
                rec_type = "tab"
            elif "search" in stem:
                rec_type = "search"

            try:
                conn = case.get_sqlite_connection(db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                tables = [r[0] for r in cursor.fetchall()]
                for table in tables:
                    t_low = table.lower()
                    t_type = rec_type
                    if "bookmark" in t_low:
                        t_type = "bookmark"
                    elif "download" in t_low:
                        t_type = "download"
                    elif "tab" in t_low:
                        t_type = "tab"
                    elif "search" in t_low:
                        t_type = "search"

                    for row_dict in case.iter_sqlite_rows(db_path, f"SELECT * FROM `{table}`"):
                        process_row(row_dict, default_browser=browser, default_type=t_type)
            except Exception as e:
                logger.debug("Error reading web SQLite %s: %s", db_path, e)

    # 2. Search TSV files
    for tsv_path in case.get_all_tsv_files():
        stem = tsv_path.stem.lower()
        if any(t in stem for t in target_hints):
            browser = "Safari"
            if "chrome" in stem:
                browser = "Chrome"
            elif "firefox" in stem:
                browser = "Firefox"
            elif "duckduckgo" in stem:
                browser = "DuckDuckGo"
            elif "onion" in stem or "ornet" in stem:
                browser = "Tor/Onion Browser"

            rec_type = "history"
            if "bookmark" in stem:
                rec_type = "bookmark"
            elif "download" in stem:
                rec_type = "download"
            elif "tab" in stem:
                rec_type = "tab"
            elif "search" in stem:
                rec_type = "search"

            try:
                for row_dict in case.iter_tsv_rows(tsv_path):
                    process_row(row_dict, default_browser=browser, default_type=rec_type)
            except Exception as e:
                logger.debug("Error reading web TSV %s: %s", tsv_path, e)

    filtered.sort(key=lambda x: x.timestamp or "")

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
