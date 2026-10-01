import zipfile
from pathlib import Path

import pytest
from pypdf import PdfWriter

from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.files import decode_plist, get_file_attachment
from tests.fixtures.generate_mock_ileapp import generate_mock_ileapp_case


@pytest.fixture
def case(tmp_path: Path):
    generate_mock_ileapp_case(tmp_path)
    app = tmp_path / "data/private/var/mobile/Containers/Shared/AppGroup/X/file"
    (app / "a").mkdir(parents=True)
    (app / "b").mkdir(parents=True)
    (app / "a/data.py").write_text("print('exfil')\n", encoding="utf-8")
    (app / "b/data.py").write_text("print('other')\n", encoding="utf-8")
    (app / "a/database.py").write_text("x = 1\n", encoding="utf-8")
    with zipfile.ZipFile(app / "a/plan.docx", "w") as z:
        z.writestr(
            "word/document.xml", "<w:document><w:p><w:t>Plan &amp; budget</w:t></w:p></w:document>"
        )
    w = PdfWriter()
    w.add_blank_page(100, 100)
    with open(app / "a/blank.pdf", "wb") as f:
        w.write(f)
    (app / "a/blob.bin").write_bytes(b"\x00\x01\x02")
    cm = CaseManager()
    cm.load_case(tmp_path)
    yield cm
    cm.close()


def test_exact_name_only_and_ambiguity_is_an_error(case: CaseManager) -> None:
    with pytest.raises(ValueError, match="2 files are named"):
        get_file_attachment(case, "data.py")  # database.py must not match either
    with pytest.raises(FileNotFoundError):
        get_file_attachment(case, "data")
    rel = "data/private/var/mobile/Containers/Shared/AppGroup/X/file/a/data.py"
    info = get_file_attachment(case, "DATA.PY", path=rel)
    assert info.text == "print('exfil')\n" and info.content_kind == "text"
    assert info.source_file == rel and info.source_ios_path == rel.removeprefix("data/")
    assert info.evidence_id.startswith("EV-") and info.row_digest == info.sha256[:16]


def test_documents_and_binaries(case: CaseManager) -> None:
    assert get_file_attachment(case, "plan.docx").text == "Plan & budget"
    pdf = get_file_attachment(case, "blank.pdf")
    assert pdf.content_kind == "pdf" and pdf.text == "" and "OCR" in pdf.note
    blob = get_file_attachment(case, "blob.bin")
    assert blob.content_kind == "binary" and blob.text is None and blob.note


def test_text_is_paged(case: CaseManager) -> None:
    info = get_file_attachment(case, "plan.docx", max_chars=4, offset=2)
    assert info.text == "an &" and info.text_chars_total == len("Plan & budget")


def test_plist_decoding_stays_inside_the_case(case: CaseManager) -> None:
    with pytest.raises(PermissionError):
        decode_plist(case, "../../../etc/passwd")
