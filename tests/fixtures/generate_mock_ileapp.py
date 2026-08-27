import csv
import sqlite3
from pathlib import Path


def generate_mock_ileapp_case(target_dir: Path) -> Path:
    """Generate a realistic mock iLEAPP output folder simulating a GrayKey / FFS extraction."""
    target_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = target_dir / "_iLEAPP_Reports_2026-08-27_08-00-00"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 1. Device Information TSV
    dev_info_path = reports_dir / "Device_Information.tsv"
    with open(dev_info_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["Key", "Value"])
        writer.writerow(["Device Name", "iPhone 14 Pro de John Doe"])
        writer.writerow(["Product Type", "iPhone15,2"])
        writer.writerow(["iOS Version", "17.4.1 (21E236)"])
        writer.writerow(["Serial Number", "F2LL70ABCD12"])
        writer.writerow(["IMEI", "354890123456789"])
        writer.writerow(["Phone Number", "+33612345678"])
        writer.writerow(["Time Zone", "Europe/Paris (UTC+2)"])
        writer.writerow(["Extraction Type", "Full File System (GrayKey)"])
        writer.writerow(["Extraction Date", "2026-08-27 06:30:00 UTC"])

    # 2. SMS & iMessage SQLite DB
    sms_db_path = reports_dir / "SMS_&_iMessage.db"
    conn_sms = sqlite3.connect(sms_db_path)
    cur_sms = conn_sms.cursor()
    cur_sms.execute(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            message_date TEXT,
            sender TEXT,
            recipient TEXT,
            message_text TEXT,
            is_from_me INTEGER,
            service TEXT,
            attachment TEXT
        )
        """
    )
    sms_data = [
        (
            1,
            "2026-08-20 14:15:00",
            "+33698765432",
            "+33612345678",
            "Salut John, rendez-vous à la tour Eiffel à 18h ?",
            0,
            "iMessage",
            None,
        ),
        (
            2,
            "2026-08-20 14:16:30",
            "+33612345678",
            "+33698765432",
            "Parfait, j'y serai avec les documents.",
            1,
            "iMessage",
            None,
        ),
        (
            3,
            "2026-08-21 09:00:00",
            "+33611223344",
            "+33612345678",
            "Votre code de confirmation bancaire est 948271",
            0,
            "SMS",
            None,
        ),
        (
            4,
            "2026-08-22 18:30:00",
            "+33612345678",
            "+33698765432",
            "Regarde la photo de l'appartement",
            1,
            "iMessage",
            "/private/var/mobile/Media/DCIM/100APPLE/IMG_0042.JPG",
        ),
    ]
    cur_sms.executemany("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)", sms_data)
    conn_sms.commit()
    conn_sms.close()

    # 3. WhatsApp Messages TSV
    wa_tsv_path = reports_dir / "WhatsApp_Messages.tsv"
    with open(wa_tsv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(
            ["Message Date", "Sender", "Recipient", "Message Content", "Status", "Service"]
        )
        writer.writerow(
            [
                "2026-08-23 11:20:00",
                "+33700112233",
                "John Doe",
                "Transfert effectué pour le projet secret.",
                "Received",
                "WhatsApp",
            ]
        )
        writer.writerow(
            [
                "2026-08-23 11:22:15",
                "John Doe",
                "+33700112233",
                "Bien reçu, merci.",
                "Sent",
                "WhatsApp",
            ]
        )

    # 4. Call History SQLite DB
    calls_db_path = reports_dir / "Call_History.db"
    conn_calls = sqlite3.connect(calls_db_path)
    cur_calls = conn_calls.cursor()
    cur_calls.execute(
        """
        CREATE TABLE call_history (
            id INTEGER PRIMARY KEY,
            call_date TEXT,
            phone_number TEXT,
            contact_name TEXT,
            call_type TEXT,
            duration TEXT,
            service TEXT
        )
        """
    )
    calls_data = [
        (1, "2026-08-20 14:10:00", "+33698765432", "Alice Dupont", "Incoming", "125", "Cellular"),
        (2, "2026-08-21 16:45:00", "+33655443322", "Bob Martin", "Missed", "0", "Cellular"),
        (3, "2026-08-22 20:00:00", "+33698765432", "Alice Dupont", "Outgoing", "05:30", "FaceTime"),
    ]
    cur_calls.executemany("INSERT INTO call_history VALUES (?, ?, ?, ?, ?, ?, ?)", calls_data)
    conn_calls.commit()
    conn_calls.close()

    # 5. Locations SQLite DB (Significant Locations & Routine)
    loc_db_path = reports_dir / "Locations.db"
    conn_loc = sqlite3.connect(loc_db_path)
    cur_loc = conn_loc.cursor()
    cur_loc.execute(
        """
        CREATE TABLE locations (
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            latitude REAL,
            longitude REAL,
            altitude REAL,
            horizontal_accuracy REAL,
            source TEXT,
            description TEXT
        )
        """
    )
    loc_data = [
        (
            1,
            "2026-08-20 18:00:00",
            48.8584,
            2.2945,
            35.0,
            5.0,
            "Significant Locations",
            "Tour Eiffel, Paris",
        ),
        (
            2,
            "2026-08-21 12:30:00",
            48.8606,
            2.3376,
            40.0,
            10.0,
            "Routine",
            "Musée du Louvre, Paris",
        ),
        (
            3,
            "2026-08-24 09:15:00",
            45.7640,
            4.8357,
            170.0,
            8.0,
            "Significant Locations",
            "Place Bellecour, Lyon",
        ),
    ]
    cur_loc.executemany("INSERT INTO locations VALUES (?, ?, ?, ?, ?, ?, ?, ?)", loc_data)
    conn_loc.commit()
    conn_loc.close()

    # 6. Apple Maps TSV
    maps_tsv_path = reports_dir / "Apple_Maps.tsv"
    with open(maps_tsv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["Timestamp", "Latitude", "Longitude", "Location Name", "Source"])
        writer.writerow(
            [
                "2026-08-20 17:30:00",
                "48.8584",
                "2.2945",
                "Tour Eiffel - Recherche itinéraire",
                "Apple Maps",
            ]
        )

    # 7. Safari Browser SQLite DB
    safari_db_path = reports_dir / "Safari_Browser.db"
    conn_safari = sqlite3.connect(safari_db_path)
    cur_safari = conn_safari.cursor()
    cur_safari.execute(
        """
        CREATE TABLE history (
            id INTEGER PRIMARY KEY,
            visit_time TEXT,
            url TEXT,
            title TEXT,
            visit_count INTEGER
        )
        """
    )
    safari_data = [
        (
            1,
            "2026-08-19 10:00:00",
            "https://www.google.com/search?q=forensic+investigation+tools",
            "Google Search",
            1,
        ),
        (
            2,
            "2026-08-19 10:05:00",
            "https://github.com/abrignoni/iLEAPP",
            "GitHub - abrignoni/iLEAPP",
            4,
        ),
        (
            3,
            "2026-08-22 14:00:00",
            "https://www.apple.com/fr/iphone/",
            "Apple iPhone - Site officiel",
            2,
        ),
    ]
    cur_safari.executemany("INSERT INTO history VALUES (?, ?, ?, ?, ?)", safari_data)
    conn_safari.commit()
    conn_safari.close()

    # 8. Installed Apps TSV
    apps_tsv_path = reports_dir / "Installed_Apps.tsv"
    with open(apps_tsv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(
            ["App Name", "Bundle ID", "Version", "Install Date", "Developer", "Permissions"]
        )
        writer.writerow(
            [
                "Signal",
                "org.whispersystems.signal",
                "7.10.0",
                "2026-01-15 10:00:00",
                "Quiet Riddle Limited",
                "Camera, Microphone, Contacts",
            ]
        )
        writer.writerow(
            [
                "WhatsApp",
                "net.whatsapp.WhatsApp",
                "24.5.75",
                "2025-11-20 09:30:00",
                "WhatsApp Inc.",
                "Camera, Location, Contacts, Photos",
            ]
        )
        writer.writerow(
            [
                "Proton Mail",
                "ch.protonmail.protonmail",
                "5.1.2",
                "2026-03-01 14:20:00",
                "Proton AG",
                "Notifications",
            ]
        )

    # 9. Apple Notes TSV (generic artifact example)
    notes_tsv_path = reports_dir / "Apple_Notes.tsv"
    with open(notes_tsv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["Title", "Creation Date", "Last Modified", "Snippet"])
        writer.writerow(
            [
                "Codes secrets",
                "2026-02-10 11:00:00",
                "2026-08-22 19:00:00",
                "Coffre-fort: 4920, Alarme: 8812",
            ]
        )
        writer.writerow(
            ["Courses", "2026-08-18 08:00:00", "2026-08-18 08:30:00", "Café, Thé, Pommes"]
        )

    return target_dir
