import hashlib
import os
import plistlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ileapp_mcp.case import CaseManager


class FileInfo(BaseModel):
    file_name: str
    absolute_path: str
    size_bytes: int
    sha256: str
    content_preview: str | None = None
    is_binary: bool


def get_file_attachment(case: CaseManager, file_name: str) -> FileInfo | None:
    """Search for a specific file/attachment within the extracted iLEAPP directory by its name."""
    if not case.is_loaded or not case.case_path:
        raise ValueError("No case loaded. Please call load_case first.")

    # We will search recursively in the case root directory
    target = file_name.lower()

    # We use os.walk to find the file
    for root, _dirs, files in os.walk(str(case.case_path)):
        for f in files:
            if target in f.lower():
                full_path = Path(root) / f
                try:
                    size = full_path.stat().st_size
                    # Hash
                    sha256_hash = hashlib.sha256()
                    is_binary = False
                    preview = ""

                    with open(full_path, "rb") as bf:
                        chunk = bf.read(4096)
                        if b"\\x00" in chunk and b"bplist" not in chunk[:6]:
                            is_binary = True

                        # compute hash completely
                        bf.seek(0)
                        for c in iter(lambda: bf.read(65536), b""):
                            sha256_hash.update(c)

                    if not is_binary and size < 1000000:  # 1MB limit for text preview
                        try:
                            with open(full_path, encoding="utf-8") as tf:
                                preview = tf.read()[:2000]
                        except UnicodeDecodeError:
                            is_binary = True

                    if full_path.suffix == ".plist" or full_path.suffix == ".bplist":
                        try:
                            with open(full_path, "rb") as bf:
                                pl = plistlib.load(bf)
                                preview = str(pl)[:2000]
                                is_binary = False
                        except Exception:
                            pass

                    return FileInfo(
                        file_name=f,
                        absolute_path=str(full_path),
                        size_bytes=size,
                        sha256=sha256_hash.hexdigest(),
                        content_preview=preview if not is_binary else None,
                        is_binary=is_binary,
                    )
                except Exception:
                    pass
    return None


def decode_plist(case: CaseManager, relative_path: str) -> dict[str, Any] | str:
    """Decode a binary plist (bplist) or standard XML plist file."""
    if not case.is_loaded or not case.case_path:
        raise ValueError("No case loaded. Please call load_case first.")

    # Resolve path
    full_path = case.case_path / relative_path
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
            if isinstance(val, dict):
                return val
            return {"parsed": val}
        except Exception as e:
            return f"Failed to decode plist: {str(e)}"
