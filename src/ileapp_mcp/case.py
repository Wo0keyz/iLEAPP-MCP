import contextlib
import csv
import hashlib
import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Stateless MCP clients (e.g. Crush) restart the server per call; set ILEAPP_MCP_RESUME_LAST_CASE=1
# to let them reload the last case. Off by default so one client cannot change another's case.
_RESUME_LAST_CASE = os.environ.get("ILEAPP_MCP_RESUME_LAST_CASE") == "1"
_STATE_FILE = os.path.join(tempfile.gettempdir(), ".ileapp_mcp_last_case")
_MAX_FILES_TO_SCAN = 2_000_000  # guard against pointing the server at a filesystem root

# a long message body must not abort the read of its file; the limit is a C long (32-bit on Windows)
csv.field_size_limit(2**31 - 1)

_PLAIN_SELECT = re.compile(r"^SELECT \* FROM `([^`]+)`( LIMIT \d+)?$", re.IGNORECASE)
# iLEAPP columns that name the iOS file a row was parsed from
_PROV_COLUMN = re.compile(
    r"^(source (file|path|database)( location)?|file location|full file path)$", re.IGNORECASE
)


_FILE_NAME = re.compile(r"^[\w.\-]+\.\w{2,12}$")


class Row(dict[str, Any]):
    """A data row plus where it came from: file, table and row number (see evidence_fields)."""

    prov: dict[str, Any]


def evidence_id(source_file: str, source_table: str | None, row_id: Any) -> str:
    """Stable identifier of one row of one file of a case export."""
    digest = hashlib.sha256(f"{source_file}|{source_table or ''}|{row_id}".encode()).hexdigest()
    return f"EV-{digest[:12]}"


def evidence_fields(row: Any) -> dict[str, Any]:
    """Provenance of a row read through CaseManager, as the fields of models.Sourced."""
    prov = getattr(row, "prov", None)
    if not prov:
        return {}
    ios_path = next(
        (str(v) for k, v in row.items() if v and _PROV_COLUMN.match(str(k))), None
    ) or prov.get("artifact_ios_path")
    if ios_path:
        # iLEAPP writes either a device path or the absolute path of its own working copy
        # (C:\...\<output>\data\private\var\...): keep the device part only.
        ios_path = ios_path.replace("\\", "/")
        in_copy = re.search(r"(?:^|/)data/(private/.*)$", ios_path)
        ios_path = (in_copy.group(1) if in_copy else ios_path).lstrip("/")
    content = "\x1f".join(f"{k}={v}" for k, v in row.items())
    return {
        "evidence_id": evidence_id(prov["source_file"], prov["source_table"], prov["row_id"]),
        "source_file": prov["source_file"],
        "source_table": prov["source_table"],
        "row_id": prov["row_id"],
        "source_ios_path": ios_path,
        # evidence_id names a position; the digest binds it to what the row contained
        "row_digest": hashlib.sha256(content.encode()).hexdigest()[:16],
    }


class CaseManager:
    """Manages discovery, indexing, and access to an iLEAPP forensic report directory."""

    def __init__(self, case_dir: str | Path | None = None) -> None:
        self.case_path: Path | None = None
        self._report_root: Path | None = None
        self._sqlite_dbs: dict[str, Path] = {}
        self._tsv_files: dict[str, Path] = {}
        self._db_connections: dict[str, sqlite3.Connection] = {}
        self._artifact_ios_source: dict[str, str] = {}
        self._lock = threading.RLock()
        self.is_loaded = False
        self.index_truncated = False
        # Files that could not be read since the last check (see server._fail_on_read_errors)
        self.read_errors: list[str] = []

        if case_dir:
            self.load_case(case_dir)
        elif _RESUME_LAST_CASE:
            # Opt-in only: resuming "the last case" silently mixes cases when several
            # clients or test runs share the machine.
            try:
                if os.path.exists(_STATE_FILE):
                    with open(_STATE_FILE, encoding="utf-8") as f:
                        saved_path = f.read().strip()
                    if saved_path and os.path.exists(saved_path):
                        self.load_case(saved_path)
            except Exception as e:
                logger.debug("Could not load saved state: %s", e)

    def load_case(self, path: str | Path) -> bool:
        """Load and index an iLEAPP case directory."""
        with self._lock:
            target_path = Path(path).resolve()
            if not target_path.exists() or not target_path.is_dir():
                raise ValueError(f"Target path does not exist or is not a directory: {target_path}")

            if self.is_loaded and self.case_path == target_path:
                return True

            self._close_connections()
            self.case_path = target_path
            self._report_root = self._find_report_root(target_path)
            self._index_files()
            self._load_artifact_sources(target_path)
            self.is_loaded = True
            logger.info("Loaded iLEAPP case from %s (root: %s)", target_path, self._report_root)

            # Persist state to survive stateless MCP clients (like Crush restarting the process)
            if _RESUME_LAST_CASE:
                try:
                    with open(_STATE_FILE, "w", encoding="utf-8") as f:
                        f.write(str(target_path))
                except Exception as e:
                    logger.debug("Could not save state: %s", e)

            return True

    def _find_report_root(self, root: Path) -> Path:
        """Find the true report root directory containing reports and databases."""
        # Check if direct directory has .db or .tsv files
        direct_files = list(root.glob("*.db")) + list(root.glob("*.tsv"))
        if direct_files:
            return root

        # Check for subdirectories like _iLEAPP_Reports_* or similar
        for child in root.iterdir():
            if child.is_dir() and "iLEAPP_Reports" in child.name:
                return child

        # Check for _Reports or Reports subdirectory
        reports_sub = root / "_Reports"
        if reports_sub.is_dir():
            return root

        return root

    def _index_files(self) -> None:
        """Index all SQLite databases and TSV/CSV files recursively in the report root."""
        self._sqlite_dbs.clear()
        self._tsv_files.clear()

        if not self._report_root or not self._report_root.exists():
            return

        # No on-disk index cache: a stale cache hides files added to the case, and unpickling
        # from a shared temp directory executes whatever another local user put there.
        self.index_truncated = False
        file_count = 0
        for p in self._report_root.rglob("*"):
            file_count += 1
            if file_count > _MAX_FILES_TO_SCAN:
                # Never silent: get_case_info reports index_truncated so callers can refuse.
                self.index_truncated = True
                logger.error(
                    "Index truncated at %d entries in %s: some artifacts are NOT indexed.",
                    _MAX_FILES_TO_SCAN,
                    self._report_root,
                )
                break

            if not p.is_file():
                continue

            suffix = p.suffix.lower()
            rel_name = p.name

            raw = self._is_raw(p)
            if suffix in {".db", ".sqlite", ".sqlite3"}:
                # a raw iOS database never shadows a report-level one of the same name
                for key in (p.stem.lower(), rel_name.lower()):
                    if not raw or key not in self._sqlite_dbs:
                        self._sqlite_dbs[key] = p
            elif suffix in {".tsv", ".csv"} and not raw:
                # CSV/TSV files of the device itself (under data/) are not iLEAPP exports
                stem = p.stem.lower()
                self._tsv_files[stem] = p
                self._tsv_files[rel_name.lower()] = p

    def get_sqlite_path(self, name_hint: str) -> Path | None:
        """Find a SQLite database path by name hint or pattern."""
        with self._lock:
            hint = name_hint.lower()
            if hint in self._sqlite_dbs:
                return self._sqlite_dbs[hint]

            for key, path in self._sqlite_dbs.items():
                if hint in key:
                    return path
            return None

    def get_tsv_path(self, name_hint: str, exact: bool = False) -> Path | None:
        """Find a TSV/CSV path by exact name, else (unless exact) by substring."""
        with self._lock:
            hint = name_hint.lower()
            if hint in self._tsv_files:
                return self._tsv_files[hint]
            if exact:
                return None

            for key, path in self._tsv_files.items():
                if hint in key:
                    return path
            return None

    def get_sqlite_connection(self, db_path: Path) -> sqlite3.Connection:
        """Get or create a read-only thread-safe SQLite connection."""
        with self._lock:
            path_str = str(db_path.resolve())
            if path_str not in self._db_connections:
                # Open in read-only mode via URI
                uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
                conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                self._db_connections[path_str] = conn
            return self._db_connections[path_str]

    def query_sqlite(
        self,
        db_path: Path,
        query: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
        limit: int = 250,
        offset: int = 0,
    ) -> tuple[list[str], list[dict[str, Any]], int]:
        """Execute a read-only query and return (columns, rows, total_count)."""
        self.validate_readonly_query(query)
        conn = self.get_sqlite_connection(db_path)

        with self._lock:
            cursor = conn.cursor()

            # Estimate total count if possible for single SELECT queries
            total_count = 0
            count_query = None
            clean_query = query.strip().rstrip(";")
            has_limit = re.search(r"\bLIMIT\b", clean_query, re.IGNORECASE) is not None

            if clean_query.upper().startswith("SELECT ") and not has_limit:
                count_query = f"SELECT COUNT(*) FROM ({clean_query})"
                try:
                    count_cursor = conn.cursor()
                    count_cursor.execute(count_query, params)
                    res = count_cursor.fetchone()
                    if res:
                        total_count = res[0]
                except Exception:
                    total_count = 0

            # Execute with pagination
            if has_limit:
                paginated_query = clean_query
            else:
                paginated_query = f"{clean_query} LIMIT {limit} OFFSET {offset}"

            cursor.execute(paginated_query, params)
            rows_raw = cursor.fetchall()
            columns = [d[0] for d in cursor.description] if cursor.description else []

            rows = []
            for row in rows_raw:
                sanitized = []
                for v in row:
                    if isinstance(v, bytes):
                        sanitized.append(v.hex()[:256] + ("..." if len(v.hex()) > 256 else ""))
                    else:
                        sanitized.append(v)
                rows.append(dict(zip(columns, sanitized, strict=False)))

            if total_count == 0:
                total_count = len(rows)

            return columns, rows, total_count

    def iter_sqlite_rows(
        self, db_path: Path, query: str, params: tuple[Any, ...] | dict[str, Any] = ()
    ) -> Generator[Row, None, None]:
        """Yield rows one by one; each row knows its database, table and rowid."""
        self.validate_readonly_query(query)
        conn = self.get_sqlite_connection(db_path)
        rel = self._rel(db_path)
        plain = _PLAIN_SELECT.match(query.strip())
        table = plain.group(1) if plain else None
        with self._lock, self._recording(rel):
            cursor = conn.cursor()
            has_rowid = False
            if plain:
                try:
                    cursor.execute(
                        f"SELECT rowid AS __rowid__, * FROM `{table}`{plain.group(2) or ''}", params
                    )
                    has_rowid = True
                except sqlite3.OperationalError:  # view or WITHOUT ROWID table
                    cursor.execute(query, params)
            else:
                cursor.execute(query, params)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            for position, row in enumerate(cursor, start=1):
                sanitized = []
                for v in row:
                    if isinstance(v, bytes):
                        sanitized.append(v.hex()[:256] + ("..." if len(v.hex()) > 256 else ""))
                    else:
                        sanitized.append(v)
                out = Row(zip(columns, sanitized, strict=False))
                rowid = out.pop("__rowid__", None) if has_rowid else None
                out.prov = {
                    "source_file": rel,
                    "source_table": table,
                    "row_id": rowid if rowid is not None else position,
                    # a raw iOS database copied under data/ keeps its device path
                    "artifact_ios_path": rel[len("data") :] if rel.startswith("data/") else None,
                }
                yield out

    def read_tsv_records(self, tsv_path: Path, delimiter: str | None = None) -> list[Row]:
        """Parse a TSV or CSV report file into a list of rows."""
        return list(self.iter_tsv_rows(tsv_path, delimiter))

    def get_all_sqlite_dbs(self) -> list[Path]:
        """Return distinct SQLite database paths discovered."""
        with self._lock:
            return sorted(set(self._sqlite_dbs.values()))

    def get_report_sqlite_dbs(self) -> list[Path]:
        """SQLite databases produced by the report tool, excluding the raw iOS files under data/."""
        with self._lock:
            return [p for p in sorted(set(self._sqlite_dbs.values())) if not self._is_raw(p)]

    def get_all_tsv_files(self) -> list[Path]:
        """Return distinct TSV/CSV file paths discovered."""
        with self._lock:
            return sorted(set(self._tsv_files.values()))

    def iter_tsv_rows(
        self, tsv_path: Path, delimiter: str | None = None
    ) -> Generator[Row, None, None]:
        """Yield TSV records one by one; each row knows its file and record number.

        A missing, unreadable or malformed file raises and is recorded in read_errors:
        an export that cannot be read must never look like an empty one.
        """

        if delimiter is None:
            delimiter = "\t" if tsv_path.suffix.lower() == ".tsv" else ","

        rel = self._rel(tsv_path)
        ios_path = self._artifact_ios_source.get(tsv_path.stem.lower())
        # newline="" lets the csv module handle line breaks inside quoted fields itself
        try:
            # errors="strict": bytes that are not UTF-8 must fail the read, not be rewritten
            with open(tsv_path, encoding="utf-8-sig", errors="strict", newline="") as f:
                reader = csv.DictReader(f, delimiter=delimiter, strict=True)
                for number, row in enumerate(reader, start=1):
                    if None in row:
                        raise csv.Error(f"record {number} has more fields than the header")
                    out = Row(
                        (str(k).strip(), str(v).strip())
                        for k, v in row.items()
                        if k is not None and v is not None
                    )
                    out.prov = {
                        "source_file": rel,
                        "source_table": None,
                        "row_id": number,
                        "artifact_ios_path": ios_path,
                    }
                    yield out
        except (csv.Error, OSError, UnicodeError) as e:
            self.read_errors.append(f"{rel}: {e}")
            raise

    @contextlib.contextmanager
    def _recording(self, rel: str) -> Generator[None, None, None]:
        """Record a database read failure in read_errors, then let it propagate."""
        try:
            yield
        except sqlite3.Error as e:
            self.read_errors.append(f"{rel}: {e}")
            raise

    def _is_raw(self, path: Path) -> bool:
        """True for a file of the device copy (any data/ directory inside the case)."""
        try:
            return "data" in path.relative_to(self.case_path or path.parent).parts[:-1]
        except ValueError:
            return False

    def _rel(self, path: Path) -> str:
        """Path relative to the case directory, as recorded in provenance."""
        try:
            return path.resolve().relative_to(self.case_path or path.parent).as_posix()
        except ValueError:
            return path.name

    def _load_artifact_sources(self, case_dir: Path) -> None:
        """Read iLEAPP's own metadata: which iOS file each artifact was parsed from."""
        self._artifact_ios_source = {}
        try:
            with open(case_dir / "_lava_data.lava", encoding="utf-8") as f:
                groups = json.load(f).get("artifacts", {})
        except (OSError, ValueError):
            return
        for group in groups.values() if isinstance(groups, dict) else []:
            for artifact in group:
                source = str(artifact.get("source_path") or "")
                # a path or a bare file name, not a phrase such as "See Table for Source DB"
                if "/" in source or "\\" in source or _FILE_NAME.match(source):
                    name = str(artifact.get("name") or "").lower()
                    self._artifact_ios_source[name] = source.replace("\\", "/")

    @staticmethod
    def validate_readonly_query(query: str) -> None:
        """Validate that a SQL statement is strictly read-only and safe."""
        normalized = query.strip()
        if not normalized:
            raise ValueError("SQL query cannot be empty.")

        # Disallow multiple statements separated by semicolon
        # Count semicolons not in strings
        cleaned = re.sub(r"'[^']*'", "", normalized)
        cleaned = re.sub(r'"[^"]*"', "", cleaned)
        if ";" in cleaned.rstrip(";"):
            raise ValueError("Multiple SQL statements are not permitted.")

        # Check start keyword
        upper = normalized.upper().strip()
        allowed_starts = ("SELECT", "WITH", "EXPLAIN", "PRAGMA TABLE_INFO", "PRAGMA TABLE_LIST")
        if not any(upper.startswith(keyword) for keyword in allowed_starts):
            raise ValueError(
                f"Only read-only queries (SELECT, WITH, EXPLAIN) are allowed. Received: {query[:30]}..."
            )

        # Blacklist dangerous SQL keywords
        forbidden_keywords = [
            r"\bDROP\b",
            r"\bDELETE\b",
            r"\bUPDATE\b",
            r"\bINSERT\b",
            r"\bALTER\b",
            r"\bCREATE\b",
            r"\bREPLACE\b",
            r"\bATTACH\b",
            r"\bDETACH\b",
            r"\bVACUUM\b",
            r"\bREINDEX\b",
            r"\bPRAGMA\s+WRITABLE_SCHEMA\b",
        ]
        for pattern in forbidden_keywords:
            if re.search(pattern, cleaned, re.IGNORECASE):
                raise ValueError(
                    f"Forbidden mutation keyword detected in SQL query matching: {pattern}"
                )

    def _close_connections(self) -> None:
        """Close all open SQLite connections."""
        for conn in self._db_connections.values():
            with contextlib.suppress(Exception):
                conn.close()
        self._db_connections.clear()

    def close(self) -> None:
        """Clean up resources."""
        with self._lock:
            self._close_connections()
            self.is_loaded = False
