"""Structural file checks before anything is parsed (PRD 5.3, 5.5).

Nothing in an uploaded file is ever executed: macros are rejected, and spreadsheet
formulas are never evaluated (only cached cell values are read).
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePath

_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")   # legacy .xls OR an encrypted .xlsx container
_ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".gz", ".tar", ".tgz", ".bz2"}
_MACRO_EXTS = {".xlsm", ".xlsb", ".xltm"}


@dataclass
class InspectionResult:
    ok: bool
    file_type: str | None = None          # "csv" | "xlsx" | "html" (an HTML table saved as .xls)
    errors: list[str] = field(default_factory=list)


def safe_filename(name: str) -> str:
    """Basename only, restricted characters (no path traversal into storage)."""
    base = PurePath(name.replace("\\", "/")).name or "upload"
    cleaned = "".join(c if c.isalnum() or c in "._- " else "_" for c in base).strip(" .")
    return (cleaned or "upload")[:120]


def inspect_file(filename: str, data: bytes, allowed_extensions: tuple[str, ...], max_bytes: int) -> InspectionResult:
    ext = PurePath(filename.lower()).suffix
    if not data:
        return InspectionResult(False, errors=["The file is empty."])
    if len(data) > max_bytes:
        return InspectionResult(False, errors=[f"The file exceeds the {max_bytes // (1024 * 1024)} MB limit."])
    if ext in _ARCHIVE_EXTS:
        return InspectionResult(False, errors=["Archive files are not accepted; upload the CSV or Excel file itself."])
    if ext in _MACRO_EXTS:
        return InspectionResult(False, errors=["Macro-enabled or binary workbooks are not accepted; save as .xlsx."])
    if ext not in allowed_extensions:
        return InspectionResult(False, errors=[f"Unsupported file type '{ext or 'none'}'. Allowed: {', '.join(allowed_extensions)}."])

    if ext == ".xlsx":
        if data.startswith(_OLE_MAGIC):
            return InspectionResult(False, errors=["The workbook is password-protected (encrypted) or not a real .xlsx file."])
        if not data.startswith(_ZIP_MAGIC):
            return InspectionResult(False, errors=["The file is not a valid .xlsx workbook (wrong file signature)."])
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
                if zf.testzip() is not None:
                    return InspectionResult(False, errors=["The workbook is corrupted."])
        except zipfile.BadZipFile:
            return InspectionResult(False, errors=["The workbook is corrupted."])
        if "[Content_Types].xml" not in names or not any(n.startswith("xl/") for n in names):
            return InspectionResult(False, errors=["The file is not a valid .xlsx workbook."])
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            return InspectionResult(False, errors=["The workbook contains macros; macros are not accepted."])
        return InspectionResult(True, file_type="xlsx")

    if ext == ".csv":
        if data.startswith(_ZIP_MAGIC) or data.startswith(_OLE_MAGIC):
            return InspectionResult(False, errors=["The file is named .csv but is a binary file."])
        if b"\x00" in data[:4096]:
            return InspectionResult(False, errors=["The CSV contains binary data; save it as UTF-8 CSV."])
        return InspectionResult(True, file_type="csv")

    if ext == ".xls":
        # Pocket HRMS saves some reports (e.g. the On Duty Report) as an HTML table named .xls. Only that is read;
        # a real binary .xls is refused (it would need another reader) - open it in Excel and save it as .xlsx.
        if data.startswith(_OLE_MAGIC) or data.startswith(_ZIP_MAGIC):
            return InspectionResult(False, errors=["This is a binary Excel 97-2003 (.xls) workbook; open it in Excel and save it as .xlsx."])
        head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
        if not head.startswith(b"<") or b"<table" not in data[:200_000].lower():
            return InspectionResult(False, errors=["The .xls file is not a readable report; open it in Excel and save it as .xlsx."])
        return InspectionResult(True, file_type="html")

    return InspectionResult(False, errors=[f"Unsupported file type '{ext}'."])
