import sqlite3
from pathlib import Path

from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.messages import get_messages


def test_get_all_messages(loaded_case: CaseManager) -> None:
    res = get_messages(loaded_case, limit=50)
    assert res.total_count >= 5  # 4 SMS/iMessage + 2 WhatsApp
    assert len(res.items) == res.total_count
    assert not res.has_more


def test_get_messages_filtered_by_app(loaded_case: CaseManager) -> None:
    wa_res = get_messages(loaded_case, app="WhatsApp")
    assert wa_res.total_count == 2
    assert all(m.app == "WhatsApp" for m in wa_res.items)


def test_get_messages_keyword_search(loaded_case: CaseManager) -> None:
    res = get_messages(loaded_case, keyword="Eiffel")
    assert res.total_count == 1
    assert "Eiffel" in (res.items[0].message_text or "")


def test_get_messages_sender_filter(loaded_case: CaseManager) -> None:
    res = get_messages(loaded_case, sender="+33698765432")
    assert res.total_count >= 1
    assert res.items[0].sender == "+33698765432"


def test_get_messages_date_range(loaded_case: CaseManager) -> None:
    res = get_messages(
        loaded_case,
        start_date="2026-08-21 00:00:00",
        end_date="2026-08-22 23:59:59",
    )
    assert res.total_count == 2


def test_get_messages_pagination(loaded_case: CaseManager) -> None:
    page1 = get_messages(loaded_case, limit=2, offset=0)
    assert len(page1.items) == 2
    assert page1.has_more
    assert page1.next_offset == 2

    page2 = get_messages(loaded_case, limit=2, offset=page1.next_offset or 0)
    assert len(page2.items) == 2
    assert page2.items[0] != page1.items[0]


def _case(
    tmp_path: Path, tsvs: dict[str, str], dbs: dict[str, list[tuple[str, str, str]]]
) -> CaseManager:
    """Build a throwaway report: TSV name -> content, db relative path -> (date, sender, text) rows."""
    for name, content in tsvs.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    for rel, rows in dbs.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE messages (message_date TEXT, sender TEXT, message_text TEXT)")
        conn.executemany("INSERT INTO messages VALUES (?, ?, ?)", rows)
        conn.commit()
        conn.close()
    case = CaseManager()
    case.load_case(tmp_path)
    return case


SIGNAL_TSV = "Timestamp\tAuthor\tMessage\n2030-01-01 10:00:00\tA\thello signal\n"


def test_report_level_database_is_read_even_when_a_tsv_shares_its_family(tmp_path: Path) -> None:
    case = _case(
        tmp_path,
        {"Signal - Messages.tsv": SIGNAL_TSV},
        {"messages.sqlite": [("2030-01-02 10:00:00", "B", "only in the database")]},
    )
    texts = {m.message_text for m in get_messages(case).items}
    assert texts == {"hello signal", "only in the database"}


def test_database_is_read_when_the_tsv_of_its_family_yields_nothing(tmp_path: Path) -> None:
    case = _case(
        tmp_path,
        {"SMS.tsv": "colA\tcolB\nx\ty\n"},
        {"sms.db": [("2030-01-02 10:00:00", "B", "real sms")]},
    )
    assert [m.message_text for m in get_messages(case).items] == ["real sms"]


def test_raw_ios_databases_under_data_are_not_mixed_in(tmp_path: Path) -> None:
    case = _case(
        tmp_path,
        {"Signal - Messages.tsv": SIGNAL_TSV},
        {"data/private/var/mobile/Library/SMS/sms.db": [("2030-01-02", "B", "raw unjoined row")]},
    )
    assert [m.message_text for m in get_messages(case).items] == ["hello signal"]


def test_database_copy_of_an_exported_message_is_not_duplicated(tmp_path: Path) -> None:
    case = _case(
        tmp_path,
        {"Signal - Messages.tsv": SIGNAL_TSV},
        {"chat.db": [("2030-01-01 10:00:00", "A", "hello signal")]},
    )
    assert get_messages(case).total_count == 1


def test_identical_messages_in_one_export_are_both_kept(tmp_path: Path) -> None:
    twice = SIGNAL_TSV + "2030-01-01 10:00:00\tA\thello signal\n"
    case = _case(tmp_path, {"Signal - Messages.tsv": twice}, {})
    assert get_messages(case).total_count == 2
