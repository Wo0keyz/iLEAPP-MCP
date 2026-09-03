import json
import sqlite3
from pathlib import Path

from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.device_info import get_device_info
from ileapp_mcp.modules.generic import get_raw_artifact_data
from ileapp_mcp.modules.health import get_health_data
from ileapp_mcp.modules.locations import get_location_history
from ileapp_mcp.modules.networks import get_network_connections
from ileapp_mcp.modules.system_state import get_system_state
from ileapp_mcp.modules.timeline import get_timeline


def test_locations_nan_and_inf_guard(tmp_path: Path) -> None:
    """Test that NaN and Inf coordinate values are sanitized and do not crash."""
    tsv_dir = tmp_path / "_TSV Exports"
    tsv_dir.mkdir(parents=True)
    loc_tsv = tsv_dir / "Location Test.tsv"
    with open(loc_tsv, "w", encoding="utf-8") as f:
        f.write("Timestamp\tLatitude\tLongitude\tDescription\n")
        f.write("2024-01-01 10:00:00\tnan\t2.3522\tInvalid Lat\n")
        f.write("2024-01-01 10:05:00\t48.8566\tinf\tInvalid Lon\n")
        f.write("2024-01-01 10:10:00\t48.8566\t2.3522\tValid Position\n")

    cm = CaseManager(tmp_path)
    res = get_location_history(cm)
    assert res.total_count == 3
    valid_record = [r for r in res.items if r.description == "Valid Position"][0]
    assert valid_record.latitude == 48.8566
    assert valid_record.longitude == 2.3522

    nan_record = [r for r in res.items if r.description == "Invalid Lat"][0]
    assert nan_record.latitude is None
    assert nan_record.longitude == 2.3522


def test_device_info_html_li_parsing(tmp_path: Path) -> None:
    """Test that iLEAPP's primary DeviceInfo.html <li><b>Label:</b> Value is properly parsed."""
    html_dir = tmp_path / "_HTML" / "_Script_Logs"
    html_dir.mkdir(parents=True)
    dev_html = html_dir / "DeviceInfo.html"
    dev_html.write_text(
        """
        <html><body>
        <b>--- <u>Device Information </u>---</b><br>
        <ul>
        <li><b>Device Name:</b> iPhone 14 Plus <span style="..."><i>(Source: deviceName)</i></span></li>
        <li><b>iOS Version:</b> 17.4.1 <span style="..."><i>(Source: lastBuild)</i></span></li>
        <li><b>Product Type:</b> iPhone14,8 <span style="..."><i>(Source: lastBuild)</i></span></li>
        <li><b>Serial Number:</b> F2LDR019Q1 <span style="..."><i>(Source: lastBuild)</i></span></li>
        <li><b>IMEI:</b> 358901234567890 <span style="..."><i>(Source: subscriberInfo)</i></span></li>
        <li><b>Phone Number:</b> +15551234567 <span style="..."><i>(Source: subscriberInfo)</i></span></li>
        <li><b>Time Zone:</b> America/New_York <span style="..."><i>(Source: timeZone)</i></span></li>
        </ul>
        </body></html>
        """,
        encoding="utf-8",
    )

    cm = CaseManager(tmp_path)
    info = get_device_info(cm)
    assert info.device_name == "iPhone 14 Plus"
    assert info.ios_version == "17.4.1"
    assert info.product_type == "iPhone14,8"
    assert info.serial_number == "F2LDR019Q1"
    assert info.imei == "358901234567890"
    assert info.phone_number == "+15551234567"
    assert info.timezone == "America/New_York"


def test_dynamic_sqlite_table_discovery(tmp_path: Path) -> None:
    """Test health, networks, and system_state query SQLite DBs where table != stem."""
    db_file = tmp_path / "Health_Custom.db"
    conn = sqlite3.connect(db_file)
    # Table name is 'activity_samples', NOT 'Health_Custom'
    conn.execute(
        "CREATE TABLE activity_samples (timestamp TEXT, metric TEXT, value TEXT, unit TEXT)"
    )
    conn.execute(
        "INSERT INTO activity_samples VALUES ('2024-02-01 08:00:00', 'Steps', '5420', 'count')"
    )
    conn.commit()
    conn.close()

    cm = CaseManager(tmp_path)
    health_res = get_health_data(cm)
    assert health_res.total_count == 1
    assert health_res.items[0].value == "5420"
    assert health_res.items[0].metric_type == "Steps"


def test_networks_dynamic_sqlite(tmp_path: Path) -> None:
    """Test network module against a SQLite DB with custom table name."""
    db_file = tmp_path / "wifi_harvest.sqlite"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE wifi_records (lastjoined TEXT, ssid TEXT, bssid TEXT)")
    conn.execute(
        "INSERT INTO wifi_records VALUES ('2024-02-01 09:00:00', 'Airport_Free_WiFi', '00:11:22:33:44:55')"
    )
    conn.commit()
    conn.close()

    cm = CaseManager(tmp_path)
    net_res = get_network_connections(cm)
    assert net_res.total_count == 1
    assert net_res.items[0].ssid_or_name == "Airport_Free_WiFi"
    assert net_res.items[0].bssid_or_mac == "00:11:22:33:44:55"


def test_system_state_dynamic_sqlite(tmp_path: Path) -> None:
    """Test system_state against KnowledgeC-like SQLite DB."""
    db_file = tmp_path / "knowledgeC.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE ZOBJECT (timestamp TEXT, state TEXT, value TEXT)")
    conn.execute("INSERT INTO ZOBJECT VALUES ('2024-02-01 22:00:00', 'Device Lock', 'Locked')")
    conn.commit()
    conn.close()

    cm = CaseManager(tmp_path)
    sys_res = get_system_state(cm)
    assert sys_res.total_count == 1
    assert sys_res.items[0].value == "Locked"


def test_timeline_tldb_fastpath(tmp_path: Path) -> None:
    """Test that get_timeline utilizes tl.db when present."""
    tl_dir = tmp_path / "_Timeline"
    tl_dir.mkdir(parents=True)
    tldb_path = tl_dir / "tl.db"

    conn = sqlite3.connect(tldb_path)
    conn.execute("CREATE TABLE data(key TEXT, activity TEXT, datalist TEXT)")
    entry = {
        "Message Text": "Secret rendezvous tonight",
        "Sender": "+33600000001",
        "Recipient": "+33600000002",
    }
    conn.execute(
        "INSERT INTO data VALUES (?, ?, ?)",
        ("2024-03-01 21:30:00", "SMS - Messages", json.dumps(entry)),
    )
    conn.commit()
    conn.close()

    cm = CaseManager(tmp_path)
    tl_res = get_timeline(cm)
    assert tl_res.total_count == 1
    assert tl_res.items[0].category == "messages"
    assert "Secret rendezvous" in tl_res.items[0].summary
    assert tl_res.items[0].timestamp == "2024-03-01 21:30:00"


def test_generic_raw_artifact_filtering(tmp_path: Path) -> None:
    """Test that get_raw_artifact_data filters SQLite properly across pagination."""
    db_path = tmp_path / "test_store.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE records (id INTEGER, name TEXT, category TEXT)")
    for i in range(100):
        cat = "target" if i % 10 == 0 else "other"
        conn.execute("INSERT INTO records VALUES (?, ?, ?)", (i, f"item_{i}", cat))
    conn.commit()
    conn.close()

    cm = CaseManager(tmp_path)
    # Filter for category=target (10 rows: 0, 10, 20... 90)
    res = get_raw_artifact_data(cm, "test_store:records", filters={"category": "target"}, limit=5)
    assert res.total_count == 10
    assert len(res.items) == 5
    assert res.has_more is True
    assert all(r["category"] == "target" for r in res.items)
