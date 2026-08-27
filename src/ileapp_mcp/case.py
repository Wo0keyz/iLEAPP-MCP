import contextlib
import csv
import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CaseManager:
    """Manages discovery, indexing, and access to an iLEAPP forensic report directory."""

    def __init__(self, case_dir: str | Path | None = None) -> None:
        self.case_path: Path | None = None
        self._report_root: Path | None = None
        self._sqlite_dbs: dict[str, Path] = {}
        self._tsv_files: dict[str, Path] = {}
        self._db_connections: dict[str, sqlite3.Connection] = {}
        self._lock = threading.RLock()
        self.is_loaded = False

        if case_dir:
            self.load_case(case_dir)

    def load_case(self, path: str | Path) -> bool:
        """Load and index an iLEAPP case directory."""
        with self._lock:
            target_path = Path(path).resolve()
            if not target_path.exists() or not target_path.is_dir():
                raise ValueError(f"Target path does not exist or is not a directory: {target_path}")

            self._close_connections()
            self.case_path = target_path
            self._report_root = self._find_report_root(target_path)
            self._index_files()
            self.is_loaded = True
            logger.info("Loaded iLEAPP case from %s (root: %s)", target_path, self._report_root)
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

        for p in self._report_root.rglob("*"):
            if not p.is_file():
                continue

            suffix = p.suffix.lower()
            rel_name = p.name

            if suffix in {".db", ".sqlite", ".sqlite3"}:
                stem = p.stem.lower()
                self._sqlite_dbs[stem] = p
                self._sqlite_dbs[rel_name.lower()] = p
            elif suffix in {".tsv", ".csv"}:
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

    def get_tsv_path(self, name_hint: str) -> Path | None:
        """Find a TSV/CSV path by name hint or pattern."""
        with self._lock:
            hint = name_hint.lower()
            if hint in self._tsv_files:
                return self._tsv_files[hint]

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
            if clean_query.upper().startswith("SELECT ") and " LIMIT " not in clean_query.upper():
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
            paginated_query = f"{clean_query} LIMIT {limit} OFFSET {offset}"
            cursor.execute(paginated_query, params)
            rows_raw = cursor.fetchall()
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = [dict(row) for row in rows_raw]

            if total_count == 0:
                total_count = len(rows)

            return columns, rows, total_count

    def read_tsv_records(
        self,
        tsv_path: Path,
        delimiter: str | None = None,
    ) -> list[dict[str, str]]:
        """Parse a TSV or CSV report file into a list of normalized dictionaries."""
        if not tsv_path.exists():
            return []

        if delimiter is None:
            delimiter = "\t" if tsv_path.suffix.lower() == ".tsv" else ","

        encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
        for enc in encodings:
            try:
                with open(tsv_path, encoding=enc, errors="replace") as f:
                    reader = csv.DictReader(f, delimiter=delimiter)
                    records: list[dict[str, str]] = []
                    if reader.fieldnames:
                        for row in reader:
                            records.append(
                                {
                                    str(k).strip(): str(v).strip()
                                    for k, v in row.items()
                                    if k is not None
                                }
                            )
                    return records
            except Exception as e:
                logger.debug("Failed reading %s with %s: %s", tsv_path, enc, e)
                continue
        return []

    def get_all_sqlite_dbs(self) -> list[Path]:
        """Return distinct SQLite database paths discovered."""
        with self._lock:
            return sorted(set(self._sqlite_dbs.values()))

    def get_all_tsv_files(self) -> list[Path]:
        """Return distinct TSV/CSV file paths discovered."""
        with self._lock:
            return sorted(set(self._tsv_files.values()))

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
