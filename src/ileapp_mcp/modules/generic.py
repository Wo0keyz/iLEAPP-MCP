import logging
from typing import Any

from ileapp_mcp.case import CaseManager
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
            logger.debug("Error indexing SQLite DB %s: %s", db_path, e)

    # 2. Inspect TSV files
    for tsv_path in case.get_all_tsv_files():
        tsv_rel = str(tsv_path.relative_to(case.case_path))
        records = case.read_tsv_records(tsv_path)
        artifacts.append(
            ArtifactInfo(
                name=tsv_path.stem,
                category=_infer_category(tsv_path.stem),
                format="tsv",
                file_path=tsv_rel,
                row_count=len(records),
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
    if any(k in lower for k in ["safari", "chrome", "bookmark", "download", "web", "history"]):
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


def get_raw_artifact_data(
    case: CaseManager,
    artifact_name: str,
    filters: dict[str, str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[dict[str, Any]]:
    """Query raw tabular data from any specific artifact (SQLite table or TSV file)."""
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
            # Sanitize table_part to prevent SQL injection via backticks
            safe_table = table_part.replace("`", "").replace("'", "")
            cols, fetched_rows, total = case.query_sqlite(
                db_path, f"SELECT * FROM `{safe_table}`", limit=limit, offset=offset
            )
            # Filter if requested
            filtered_rows = fetched_rows
            if filters:
                filtered_rows = [
                    r
                    for r in fetched_rows
                    if all(
                        k in r and str(v).lower() in str(r[k]).lower() for k, v in filters.items()
                    )
                ]
            has_more = (offset + limit) < total
            return PaginatedResult[dict[str, Any]](
                items=filtered_rows,
                total_count=total,
                has_more=has_more,
                limit=limit,
                offset=offset,
                next_offset=(offset + limit) if has_more else None,
            )

    # 2. Try TSV file match
    tsv_path = case.get_tsv_path(artifact_name)
    if tsv_path:
        all_tsv_records = case.read_tsv_records(tsv_path)
        if filters:
            all_tsv_records = [
                r
                for r in all_tsv_records
                if all(k in r and str(v).lower() in str(r[k]).lower() for k, v in filters.items())
            ]
        total = len(all_tsv_records)
        page = all_tsv_records[offset : offset + limit]
        has_more = (offset + limit) < total
        return PaginatedResult[dict[str, Any]](
            items=page,  # type: ignore
            total_count=total,
            has_more=has_more,
            limit=limit,
            offset=offset,
            next_offset=(offset + limit) if has_more else None,
        )

    # 3. Try finding a SQLite table with that name across all databases
    for db_path in case.get_all_sqlite_dbs():
        try:
            conn = case.get_sqlite_connection(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (artifact_name,)
            )
            if cursor.fetchone():
                safe_artifact = artifact_name.replace("`", "").replace("'", "")
                cols, fetched_rows, total = case.query_sqlite(
                    db_path, f"SELECT * FROM `{safe_artifact}`", limit=limit, offset=offset
                )
                has_more = (offset + limit) < total
                return PaginatedResult[dict[str, Any]](
                    items=fetched_rows,
                    total_count=total,
                    has_more=has_more,
                    limit=limit,
                    offset=offset,
                    next_offset=(offset + limit) if has_more else None,
                )
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
    columns, rows, total_count = case.query_sqlite(target_db_path, query, limit=max_rows, offset=0)

    return SqlQueryResult(
        query=query,
        db_name=target_db_path.name,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=total_count > len(rows),
    )
