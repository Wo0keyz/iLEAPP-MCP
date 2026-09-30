"""Provenance must be real: following (source_file, source_table, row_id) leads back to the row."""

import csv
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.apps import get_installed_apps
from ileapp_mcp.modules.calls import get_call_history
from ileapp_mcp.modules.device_info import get_device_info
from ileapp_mcp.modules.generic import get_raw_artifact_data
from ileapp_mcp.modules.health import get_health_data
from ileapp_mcp.modules.identities import get_cloud_identities
from ileapp_mcp.modules.locations import get_location_history
from ileapp_mcp.modules.messages import get_messages
from ileapp_mcp.modules.networks import get_network_connections
from ileapp_mcp.modules.notes import get_notes_and_memos
from ileapp_mcp.modules.photos import get_photos_metadata
from ileapp_mcp.modules.search import global_keyword_search
from ileapp_mcp.modules.system_state import get_system_state
from ileapp_mcp.modules.web import get_web_activity

TYPED_TOOLS: list[Callable[..., Any]] = [
    get_messages,
    get_call_history,
    get_installed_apps,
    get_web_activity,
    get_location_history,
    get_network_connections,
    get_notes_and_memos,
    get_system_state,
    get_photos_metadata,
    get_health_data,
]


def _source_row(case_dir: Path, rec: dict[str, Any]) -> list[str]:
    """Re-read the row a record claims to come from, without going through the server code."""
    path = case_dir / rec["source_file"]
    if rec["source_table"]:
        conn = sqlite3.connect(path)
        row = conn.execute(
            f"SELECT * FROM `{rec['source_table']}` WHERE rowid = ?", (rec["row_id"],)
        ).fetchone()
        conn.close()
        return [str(v) for v in row]
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t" if path.suffix == ".tsv" else ","))
    return [str(v) for v in rows[rec["row_id"] - 1].values()]


def test_every_typed_record_points_back_to_its_row(
    loaded_case: CaseManager, mock_case_dir: Path
) -> None:
    checked = 0
    for tool in TYPED_TOOLS:
        for item in tool(loaded_case, limit=250).items:
            rec = item.model_dump()
            assert rec["evidence_id"] and rec["source_file"] and rec["row_id"], (tool.__name__, rec)
            source_values = _source_row(mock_case_dir.resolve(), rec)
            own = [
                str(v)
                for k, v in rec.items()
                if isinstance(v, str) and k not in ("evidence_id", "source_file", "source_table")
            ]
            assert any(v in source_values for v in own), (tool.__name__, rec, source_values)
            checked += 1
    assert checked >= 20


def test_evidence_ids_are_stable_and_unique(mock_case_dir: Path) -> None:
    def ids() -> list[str]:
        case = CaseManager()
        case.load_case(mock_case_dir)
        found = [str(m.evidence_id) for m in get_messages(case, limit=250).items]
        case.close()
        return found

    first, second = ids(), ids()
    assert first == second
    assert len(set(first)) == len(first)


def test_raw_rows_and_search_hits_carry_provenance(
    loaded_case: CaseManager, mock_case_dir: Path
) -> None:
    raw = get_raw_artifact_data(loaded_case, "WhatsApp_Messages", exact=True).items
    assert raw and all(r["_prov"]["row_id"] == i for i, r in enumerate(raw, start=1))
    assert raw[0]["_prov"]["source_file"].endswith("WhatsApp_Messages.tsv")

    hit = global_keyword_search(loaded_case, "Eiffel").items[0]
    assert "Eiffel" in " ".join(_source_row(mock_case_dir.resolve(), hit.model_dump()))

    table = get_raw_artifact_data(loaded_case, "SMS_&_iMessage:messages").items
    assert table[0]["_prov"]["source_table"] == "messages"


def test_ios_source_path_comes_from_ileapp_metadata_or_the_row(tmp_path: Path) -> None:
    (tmp_path / "Signal - Messages.tsv").write_text(
        "Timestamp\tAuthor\tMessage\n2030-01-01 10:00:00\tA\thello\n", encoding="utf-8"
    )
    (tmp_path / "WiFi Known Networks.tsv").write_text(
        "SSID\tSource File\nhome\tC:\\Users\\x\\out\\data\\private\\var\\preferences\\wifi.plist\n",
        encoding="utf-8",
    )
    (tmp_path / "Orphan.tsv").write_text("A\nb\n", encoding="utf-8")
    lava = {
        "artifacts": {
            "Chats": [
                {
                    "name": "Signal - Messages",
                    "source_path": "private\\var\\mobile\\signal.sqlite",
                },
                {"name": "Orphan", "source_path": "See Table for Source DB"},
            ]
        }
    }
    (tmp_path / "_lava_data.lava").write_text(json.dumps(lava), encoding="utf-8")
    case = CaseManager()
    case.load_case(tmp_path)

    assert get_messages(case).items[0].source_ios_path == "private/var/mobile/signal.sqlite"
    wifi = get_raw_artifact_data(case, "WiFi Known Networks", exact=True).items[0]
    assert wifi["_prov"]["source_ios_path"] == "private/var/preferences/wifi.plist"
    # unknown stays unknown: never a made-up path
    orphan = get_raw_artifact_data(case, "Orphan", exact=True).items[0]
    assert orphan["_prov"]["source_ios_path"] is None
    case.close()


def test_device_info_and_identities_name_their_sources(loaded_case: CaseManager) -> None:
    device = get_device_info(loaded_case)
    assert device.serial_number and device.sources["serial_number"]["source_file"]
    identities = get_cloud_identities(loaded_case)
    for name in identities.wifi_networks + identities.bluetooth_devices:
        assert identities.sources[name]["evidence_id"]


def test_multiline_field_keeps_record_numbers(tmp_path: Path) -> None:
    (tmp_path / "Signal - Messages.tsv").write_text(
        'Timestamp\tAuthor\tMessage\n2030-01-01 10:00:00\tA\t"line one\nline two"\n'
        "2030-01-01 10:01:00\tB\tsecond\n",
        encoding="utf-8",
    )
    case = CaseManager()
    case.load_case(tmp_path)
    second = next(m for m in get_messages(case).items if m.message_text == "second")
    assert second.row_id == 2
    hit = global_keyword_search(case, "second").items[0]
    assert hit.row_id == 2
    case.close()


def test_sqlite_row_provenance_does_not_depend_on_the_filter(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "notes.db")
    conn.execute("CREATE TABLE msgs (id INTEGER PRIMARY KEY, body TEXT)")
    conn.executemany(
        "INSERT INTO msgs VALUES (?, ?)", [(10, "alpha"), (20, "bravo"), (30, "charlie")]
    )
    conn.commit()
    conn.close()
    case = CaseManager()
    case.load_case(tmp_path)
    everything = get_raw_artifact_data(case, "notes:msgs").items
    filtered = get_raw_artifact_data(case, "notes:msgs", filters={"body": "bravo"}).items
    bravo = next(r for r in everything if r["body"] == "bravo")
    assert filtered[0]["_prov"] == bravo["_prov"] and bravo["_prov"]["row_id"] == 20
    assert len({r["_prov"]["evidence_id"] for r in everything}) == 3
    case.close()


def test_row_digest_changes_when_the_row_changes(tmp_path: Path) -> None:
    path = tmp_path / "Notes.tsv"
    path.write_text("Title\tContent\nliste\tacheter du pain\n", encoding="utf-8")
    case = CaseManager()
    case.load_case(tmp_path)
    before = get_raw_artifact_data(case, "Notes", exact=True).items[0]["_prov"]
    path.write_text("Title\tContent\nliste\tacheter du vin\n", encoding="utf-8")
    after = get_raw_artifact_data(case, "Notes", exact=True).items[0]["_prov"]
    assert before["evidence_id"] == after["evidence_id"]  # same position
    assert before["row_digest"] != after["row_digest"]  # different content
    case.close()
