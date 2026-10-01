import hashlib
import html
import os
import plistlib
import re
import zipfile
from pathlib import Path
from typing import Any

from pydantic import Field

from ileapp_mcp.case import CaseManager, evidence_id
from ileapp_mcp.models import Sourced


class FileInfo(Sourced):
    """A file of the extraction, its fingerprint and, when it has one, its text."""

    file_name: str
    size_bytes: int
    sha256: str
    content_kind: str = Field(description="text, pdf, docx or binary")
    text: str | None = Field(
        default=None, description="Extracted text, from `offset`, at most `max_chars`"
    )
    text_chars_total: int = Field(default=0, description="Length of the whole extracted text")
    note: str | None = Field(default=None, description="Why no text was extracted, if none was")


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    xml = re.sub(r"</w:p>", "\n", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml)).strip()


def _pdf_text(path: Path) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:  # optional extra: pip install ileapp-mcp[documents]
        return None
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages).strip()


def _extract_text(path: Path) -> tuple[str, str | None, str | None]:
    """(kind, text or None, note)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _pdf_text(path)
        if text is None:
            return "pdf", None, "PDF text not extracted: pypdf is not installed"
        return (
            "pdf",
            text,
            None if text else "PDF without a text layer (scanned image?): OCR needed",
        )
    if suffix == ".docx":
        return "docx", _docx_text(path), None
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        return "binary", None, "binary file: no text"
    try:
        return "text", data.decode("utf-8"), None
    except UnicodeDecodeError:
        return "binary", None, "not valid UTF-8: no text"


def get_file_attachment(
    case: CaseManager,
    file_name: str,
    path: str | None = None,
    max_chars: int = 20000,
    offset: int = 0,
) -> FileInfo:
    """A file of the extraction whose name is exactly `file_name` (case-insensitive).

    Several files with that name: an error lists them, and `path` (relative to the case) picks one.
    Nothing outside the case directory is ever read.
    """
    if not case.is_loaded or not case.case_path:
        raise ValueError("No case loaded. Please call load_case first.")
    root = case.case_path.resolve()
    target = file_name.strip().lower()
    matches = sorted(
        Path(d) / f for d, _dirs, files in os.walk(root) for f in files if f.lower() == target
    )
    if path is not None:
        matches = [m for m in matches if m.relative_to(root).as_posix() == path.strip().lstrip("/")]
    if not matches:
        raise FileNotFoundError(
            f"no file named exactly {file_name!r} in the case" + (f" at {path!r}" if path else "")
        )
    if len(matches) > 1:
        listed = "; ".join(m.relative_to(root).as_posix() for m in matches[:20])
        raise ValueError(
            f"{len(matches)} files are named {file_name!r}: pass `path` to choose one ({listed})"
        )
    full = matches[0]
    if not full.resolve().is_relative_to(root):  # symlink leading out of the case
        raise PermissionError(f"{full} points outside the case directory")
    rel = full.relative_to(root).as_posix()
    sha = hashlib.sha256(full.read_bytes()).hexdigest()
    kind, text, note = _extract_text(full)
    max_chars = max(1, min(max_chars, 100000))
    offset = max(0, offset)
    in_copy = re.search(r"(?:^|/)data/(private/.*)$", rel)
    return FileInfo(
        evidence_id=evidence_id(rel, None, "file"),
        source_file=rel,
        source_table=None,
        row_id="file",
        source_ios_path=in_copy.group(1) if in_copy else None,
        row_digest=sha[:16],
        file_name=full.name,
        size_bytes=full.stat().st_size,
        sha256=sha,
        content_kind=kind,
        text=text[offset : offset + max_chars] if text is not None else None,
        text_chars_total=len(text or ""),
        note=note,
    )


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, bytes):
        return obj.hex()
    elif isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


def decode_plist(case: CaseManager, relative_path: str) -> dict[str, Any] | str:
    """Decode a binary plist (bplist) or standard XML plist file."""
    if not case.is_loaded or not case.case_path:
        raise ValueError("No case loaded. Please call load_case first.")

    # Resolve path, never outside the case directory
    root = case.case_path.resolve()
    full_path = (root / relative_path).resolve()
    if not full_path.is_relative_to(root):
        raise PermissionError(f"{relative_path} is outside the case directory")
    if not full_path.exists() or not full_path.is_file():
        # Try finding it globally
        for root, _dirs, files in os.walk(str(case.case_path)):
            if relative_path in files:
                full_path = Path(root) / relative_path
                break

    if not full_path.exists():
        raise FileNotFoundError(f"File {relative_path} not found.")

    with open(full_path, "rb") as f:
        try:
            val = plistlib.load(f)
            safe_val = _json_safe(val)
            if isinstance(safe_val, dict):
                return safe_val
            return {"parsed": safe_val}
        except Exception as e:
            return f"Failed to decode plist: {str(e)}"
