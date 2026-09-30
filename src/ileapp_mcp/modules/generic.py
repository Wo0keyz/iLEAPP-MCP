import logging
from typing import Any

from ileapp_mcp.case import CaseManager, evidence_fields
from ileapp_mcp.models import ArtifactInfo, PaginatedResult, SqlQueryResult

logger = logging.getLogger(__name__)


def list_available_artifacts(case: CaseManager) -> list[ArtifactInfo]:
    """Discover and catalog all parsed artifacts (SQLite tables and TSV files) in the case directory."""
    if not case.is_loaded or not case.case_path:
        raise ValueError("No case loaded. Please call load_case first.")

    artifacts: list[ArtifactInfo] = []

    # 1. Inspect SQLite databases and their tables
    for db_path in case.get_all_sqlite_dbs():
        db_rel = str(db_path.relative_to(case.case_path))
        try:
            conn = case.get_sqlite_connection(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            tables = [r[0] for r in cursor.fetchall()]
            for table in tables:
                row_count = None
                try:
                    count_cursor = conn.cursor()
                    count_cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                    c_res = count_cursor.fetchone()
                    if c_res:
                        row_count = c_res[0]
                except Exception:
                    pass

                artifacts.append(
                    ArtifactInfo(
                        name=f"{db_path.stem}:{table}",
                        category=_infer_category(table),
                        format="sqlite",
                        file_path=db_rel,
                        row_count=row_count,
                        description=f"Table '{table}' inside database {db_path.name}",
                    )
                )
        except Exception as e:
            logger.warning("Error indexing SQLite DB %s: %s", db_path, e)

    # 2. Inspect TSV files using fast line counting
    for tsv_path in case.get_all_tsv_files():
        tsv_rel = str(tsv_path.relative_to(case.case_path))
        row_count = None
        try:
            with open(tsv_path, "rb") as f:
                # Count non-empty lines minus header
                lines = sum(1 for line in f if line.strip())
                row_count = max(0, lines - 1)
        except Exception:
            pass

        artifacts.append(
            ArtifactInfo(
                name=tsv_path.stem,
                category=_infer_category(tsv_path.stem),
                format="tsv",
                file_path=tsv_rel,
                row_count=row_count,
                description=f"Tabular export {tsv_path.name}",
            )
        )

    artifacts.sort(key=lambda x: (x.category, x.name))
    return artifacts


def _infer_category(name: str) -> str:
    """Infer high-level category from table or file stem."""
    lower = name.lower()
    if any(k in lower for k in ["sms", "message", "imessage", "whatsapp", "chat", "telegram"]):
        return "Communications/Messages"
    if any(k in lower for k in ["call", "facetime", "voip"]):
        return "Communications/Calls"
    if any(
        k in lower
        for k in ["safari", "chrome", "bookmark", "download", "web", "history", "firefox"]
    ):
        return "Web Browsing"
    if any(
        k in lower for k in ["location", "routine", "map", "gps", "cell", "wifi", "significant"]
    ):
        return "Geo/Location"
    if any(k in lower for k in ["app", "bundle", "permission", "knowledgec", "biome"]):
        return "Applications/System"
    if any(k in lower for k in ["device", "info", "build", "battery", "power"]):
        return "Device Information"
    if any(k in lower for k in ["photo", "media", "camera", "exif", "album"]):
        return "Media/Photos"
    if any(k in lower for k in ["note", "health", "voice", "calendar", "contact"]):
        return "Personal Data"
    return "Other Artifacts"


def _truncate_huge_fields(row: dict[str, Any], max_len: int = 1000) -> dict[str, Any]:
    """Truncate extremely long strings in raw rows to prevent LLM context explosion."""
    truncated = {}
    for k, v in row.items():
        if isinstance(v, str) and len(v) > max_len:
            truncated[k] = v[:max_len] + f"... <truncated {len(v) - max_len} more characters>"
        else:
            truncated[k] = v
    return truncated


def _sqlite_table_page(
    case: CaseManager,
    db_path: Any,
    table: str,
    filters: dict[str, str],
    limit: int,
    offset: int,
) -> PaginatedResult[dict[str, Any]]:
    """One page of a SQLite table. Provenance is the row's rowid, whatever the filter.

    The filter is applied here on rows that already carry their rowid, so the same row always
    gets the same evidence_id (a position in a filtered result would change with the filter).
    """
    page: list[dict[str, Any]] = []
    total = 0
    for row in case.iter_sqlite_rows(db_path, f"SELECT * FROM `{table}`"):
        if not all(k in row and str(v).lower() in str(row[k]).lower() for k, v in filters.items()):
            continue
        total += 1
        if offset < total <= offset + limit:
            page.append({**_truncate_huge_fields(row), "_prov": evidence_fields(row)})
    has_more = (offset + limit) < total
    return PaginatedResult[dict[str, Any]](
        items=page,
        total_count=total,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=(offset + limit) if has_more else None,
    )


def get_raw_artifact_data(
    case: CaseManager,
    artifact_name: str,
    filters: dict[str, str] | None = None,
    limit: int = 50,
    offset: int = 0,
    exact: bool = False,
) -> PaginatedResult[dict[str, Any]]:
    """Query raw tabular data from any specific artifact (SQLite table or TSV file).

    With exact=True only a TSV export whose name is exactly artifact_name is accepted: the
    default lookup falls back to substring matching and can return a different artifact.
    """
    if not case.is_loaded:
        raise ValueError("No case loaded. Please call load_case first.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)
    filters = filters or {}

    # 1. If artifact is in "db_name:table_name" format
    if ":" in artifact_name:
        db_part, table_part = artifact_name.split(":", 1)
        db_path = case.get_sqlite_path(db_part)
        if db_path:
            safe_table = table_part.replace("`", "").replace("'", "")
            return _sqlite_table_page(case, db_path, safe_table, filters, limit, offset)

    # 2. Try TSV file match
    tsv_path = case.get_tsv_path(artifact_name, exact=exact)
    if tsv_path:
        matched: list[dict[str, Any]] = []
        total = 0
        for r in case.iter_tsv_rows(tsv_path):
            if filters and not all(
                k in r and str(v).lower() in str(r[k]).lower() for k, v in filters.items()
            ):
                continue
            total += 1
            if len(matched) < offset + limit:
                matched.append({**_truncate_huge_fields(r), "_prov": evidence_fields(r)})

        page = matched[offset : offset + limit]
        has_more = (offset + limit) < total
        return PaginatedResult[dict[str, Any]](
            items=page,
            total_count=total,
            has_more=has_more,
            limit=limit,
            offset=offset,
            next_offset=(offset + limit) if has_more else None,
        )

    # 3. Try finding a SQLite table with that name across all databases
    for db_path in [] if exact else case.get_all_sqlite_dbs():
        try:
            conn = case.get_sqlite_connection(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (artifact_name,)
            )
            if cursor.fetchone():
                safe_artifact = artifact_name.replace("`", "").replace("'", "")
                return _sqlite_table_page(case, db_path, safe_artifact, filters, limit, offset)
        except Exception:
            pass

    raise ValueError(f"Artifact '{artifact_name}' not found as a SQLite table or TSV file.")


def run_readonly_sql(
    case: CaseManager,
    query: str,
    db_name: str | None = None,
    max_rows: int = 100,
) -> SqlQueryResult:
    """Execute a safe, read-only SQL query against any discovered SQLite database in the case."""
    if not case.is_loaded:
        raise ValueError("No case loaded. Please call load_case first.")

    target_db_path = None
    all_dbs = case.get_all_sqlite_dbs()

    if not all_dbs:
        raise ValueError("No SQLite databases found in the current iLEAPP case directory.")

    if db_name:
        target_db_path = case.get_sqlite_path(db_name)
        if not target_db_path:
            raise ValueError(f"SQLite database '{db_name}' not found.")
    else:
        # Default to first available or consolidated DB
        for db in all_dbs:
            if "report" in db.stem.lower():
                target_db_path = db
                break
        if not target_db_path:
            target_db_path = all_dbs[0]

    max_rows = max(1, min(max_rows, 500))
    cols, rows, total = case.query_sqlite(target_db_path, query, limit=max_rows, offset=0)

    safe_rows = [_truncate_huge_fields(r) for r in rows]

    return SqlQueryResult(
        query=query,
        db_name=target_db_path.name,
        columns=cols,
        rows=safe_rows,
        row_count=len(safe_rows),
        truncated=total > max_rows,
    )
