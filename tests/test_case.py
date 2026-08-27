from pathlib import Path

import pytest

from ileapp_mcp.case import CaseManager


def test_load_nonexistent_directory() -> None:
    case = CaseManager()
    with pytest.raises(ValueError, match="does not exist"):
        case.load_case(Path("C:/nonexistent_directory_12345"))


def test_case_indexing(loaded_case: CaseManager) -> None:
    assert loaded_case.is_loaded
    assert loaded_case.case_path is not None

    dbs = loaded_case.get_all_sqlite_dbs()
    tsvs = loaded_case.get_all_tsv_files()

    assert len(dbs) >= 3  # SMS, Calls, Locations, Safari
    assert len(tsvs) >= 3  # Device Info, WhatsApp, Maps, Apps, Notes

    sms_db = loaded_case.get_sqlite_path("sms")
    assert sms_db is not None
    assert "SMS_&_iMessage.db" in sms_db.name

    dev_tsv = loaded_case.get_tsv_path("device_info")
    assert dev_tsv is not None


def test_validate_readonly_sql() -> None:
    # Valid queries
    CaseManager.validate_readonly_query("SELECT * FROM messages")
    CaseManager.validate_readonly_query("SELECT id, text FROM messages WHERE id = 1")
    CaseManager.validate_readonly_query("WITH recent AS (SELECT * FROM calls) SELECT * FROM recent")
    CaseManager.validate_readonly_query("EXPLAIN QUERY PLAN SELECT * FROM messages")

    # Invalid empty query
    with pytest.raises(ValueError, match="cannot be empty"):
        CaseManager.validate_readonly_query("   ")

    # Invalid multiple statements
    with pytest.raises(ValueError, match="Multiple SQL statements"):
        CaseManager.validate_readonly_query("SELECT * FROM messages; SELECT * FROM calls")

    # Invalid mutation queries (disallowed start or forbidden keywords)
    with pytest.raises(ValueError, match="Only read-only queries"):
        CaseManager.validate_readonly_query("DROP TABLE messages")

    with pytest.raises(ValueError, match="Only read-only queries"):
        CaseManager.validate_readonly_query("DELETE FROM messages WHERE id = 1")

    with pytest.raises(ValueError, match="Only read-only queries"):
        CaseManager.validate_readonly_query("UPDATE messages SET text = 'hacked'")

    with pytest.raises(ValueError, match="Only read-only queries"):
        CaseManager.validate_readonly_query("INSERT INTO messages VALUES (1, 'test')")

    with pytest.raises(ValueError, match="Forbidden mutation keyword"):
        CaseManager.validate_readonly_query("SELECT * FROM (ATTACH 'evil.db' AS evil)")
