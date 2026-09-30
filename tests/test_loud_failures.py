"""An export that cannot be read must fail the call, never look like an empty export."""

import csv
import sqlite3
from pathlib import Path

import pytest

from ileapp_mcp import server
from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.generic import get_raw_artifact_data
from ileapp_mcp.modules.messages import get_messages

HEADER = "Timestamp\tAuthor\tMessage\n"
ROW = "2030-01-01 10:00:0{i}\tA\tmessage {i}\n"


def _load(tmp_path: Path) -> CaseManager:
    case = CaseManager()
    case.load_case(tmp_path)
    return case


def test_very_long_field_is_read_not_dropped(tmp_path: Path) -> None:
    body = "x" * 300_000  # above the csv module's default 131072 limit
    (tmp_path / "Signal - Messages.tsv").write_text(
        HEADER + ROW.format(i=1) + f"2030-01-01 10:00:02\tA\t{body}\n" + ROW.format(i=3),
        encoding="utf-8",
    )
    msgs = get_messages(_load(tmp_path)).items
    assert [len(m.message_text or "") for m in msgs] == [9, 300_000, 9]


def test_malformed_tsv_raises(tmp_path: Path) -> None:
    (tmp_path / "Signal - Messages.tsv").write_text(
        HEADER + '2030-01-01 10:00:01\tA\t"never closed\n' + ROW.format(i=2), encoding="utf-8"
    )
    with pytest.raises(csv.Error):
        get_raw_artifact_data(_load(tmp_path), "Signal - Messages", exact=True)


def test_tool_fails_when_a_file_vanished_or_is_corrupt(tmp_path: Path) -> None:
    good = tmp_path / "Safari Browser - History.tsv"
    good.write_text(
        "Visit Timestamp\tTitle\tURL\n2030-01-01 10:00:00\tt\thttps://x\n", encoding="utf-8"
    )
    server.case_manager.load_case(tmp_path)
    assert server.get_web_activity().total_count == 1

    good.unlink()  # still in the index: the module's own try/except would hide this
    with pytest.raises(ValueError, match="Unreadable export file"):
        server.get_web_activity()
    server.case_manager.close()


def test_device_csv_files_are_not_exports_and_never_shadow_them(tmp_path: Path) -> None:
    (tmp_path / "Notes.tsv").write_text("Title\tContent\nreal\texport row\n", encoding="utf-8")
    raw_dir = tmp_path / "data" / "private" / "var"
    raw_dir.mkdir(parents=True)
    (raw_dir / "Notes.csv").write_text("Title,Content\nforeign,device file\n", encoding="utf-8")
    case = _load(tmp_path)
    assert [p.name for p in case.get_all_tsv_files()] == ["Notes.tsv"]
    assert get_raw_artifact_data(case, "Notes", exact=True).items[0]["Title"] == "real"


def _db(path: Path, rows: list[tuple[str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE messages (message_date TEXT, sender TEXT, message_text TEXT)")
    conn.executemany("INSERT INTO messages VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_raw_database_in_a_nested_report_layout_is_not_scanned(tmp_path: Path) -> None:
    report = tmp_path / "iLEAPP_Reports_2030"
    (report / "_TSV Exports").mkdir(parents=True)
    (report / "_TSV Exports" / "SMS.tsv").write_text(HEADER + ROW.format(i=1), encoding="utf-8")
    _db(report / "data" / "private" / "var" / "sms.db", [("1893661200", "B", "raw unjoined row")])
    assert [m.message_text for m in get_messages(_load(tmp_path)).items] == ["message 1"]


def test_identical_rows_of_a_report_database_are_both_kept(tmp_path: Path) -> None:
    _db(
        tmp_path / "chat.db",
        [("2030-01-01 10:00:00", "A", "ok"), ("2030-01-01 10:00:00", "A", "ok")],
    )
    assert get_messages(_load(tmp_path)).total_count == 2


def test_rows_without_content_are_counted_not_hidden(tmp_path: Path) -> None:
    (tmp_path / "Signal - Messages.tsv").write_text(
        HEADER + ROW.format(i=1) + "2030-01-01 10:00:05\tA\t\n", encoding="utf-8"
    )
    res = get_messages(_load(tmp_path))
    assert (res.total_count, res.skipped_empty) == (1, 1)
