import pytest

from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.generic import (
    get_raw_artifact_data,
    list_available_artifacts,
    run_readonly_sql,
)


def test_list_available_artifacts(loaded_case: CaseManager) -> None:
    artifacts = list_available_artifacts(loaded_case)
    assert len(artifacts) >= 5

    names = [a.name for a in artifacts]
    assert any("SMS_&_iMessage" in n for n in names)
    assert any("Apple_Notes" in n for n in names)


def test_get_raw_artifact_tsv(loaded_case: CaseManager) -> None:
    res = get_raw_artifact_data(loaded_case, "Apple_Notes")
    assert res.total_count == 2
    titles = [r["Title"] for r in res.items]
    assert "Codes secrets" in titles


def test_get_raw_artifact_sqlite(loaded_case: CaseManager) -> None:
    res = get_raw_artifact_data(loaded_case, "SMS_&_iMessage:messages")
    assert res.total_count == 4
    assert len(res.items) == 4


def test_run_readonly_sql_success(loaded_case: CaseManager) -> None:
    result = run_readonly_sql(
        loaded_case,
        query="SELECT id, message_text, sender FROM messages WHERE is_from_me = 1",
        db_name="sms",
    )
    assert result.row_count == 2
    assert "message_text" in result.columns
    assert not result.truncated


def test_run_readonly_sql_rejection(loaded_case: CaseManager) -> None:
    with pytest.raises(ValueError, match="Only read-only queries"):
        run_readonly_sql(
            loaded_case,
            query="DELETE FROM messages WHERE id = 1",
            db_name="sms",
        )


def test_run_readonly_sql_with_limit(loaded_case: CaseManager) -> None:
    result = run_readonly_sql(
        loaded_case,
        query="SELECT id, message_text FROM messages LIMIT 1",
        db_name="sms",
    )
    assert result.row_count == 1
    assert "message_text" in result.columns
    assert not result.truncated
