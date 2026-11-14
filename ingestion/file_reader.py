"""Read CSV/XLSX into header + rows of strings. Values are never interpreted here:
typing happens in validation against the dataset's approved schema."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, time

from openpyxl import load_workbook

MAX_ROWS = 200_000


class ReadError(Exception):
    pass


@dataclass
class Table:
    columns: list[str]
    rows: list[dict[str, str]]          # header -> raw string ("" for blank)
    row_numbers: list[int]              # 1-based line/row numbers in the source file
    sheets: list[str]


def _cell_to_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d") if value.time() == time(0, 0) else value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _unique_headers(raw: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, h in enumerate(raw):
        name = h.strip() or f"column_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        out.append(name)
    return out


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ReadError("The CSV encoding is not supported; save it as UTF-8 CSV.")


def _build(header: list, body: list[list], first_row_number: int, sheets: list[str]) -> Table:
    columns = _unique_headers([_cell_to_str(h) for h in header])
    rows, numbers = [], []
    for offset, raw in enumerate(body):
        values = [_cell_to_str(v) for v in raw]
        values += [""] * (len(columns) - len(values))
        rows.append(dict(zip(columns, values[: len(columns)])))
        numbers.append(first_row_number + offset)
        if len(rows) > MAX_ROWS:
            raise ReadError(f"The file has more than {MAX_ROWS:,} rows.")
    return Table(columns, rows, numbers, sheets)


def read_table(data: bytes, file_type: str, sheet: str | None = None, header_row: int = 1) -> Table:
    if header_row < 1:
        raise ReadError("Header row must be 1 or more.")
    if file_type == "csv":
        text = _decode(data)
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        lines = list(csv.reader(io.StringIO(text), dialect))
        if len(lines) < header_row:
            raise ReadError("The file has no header row.")
        return _build(lines[header_row - 1], lines[header_row:], header_row + 1, [])

    if file_type == "xlsx":
        try:
            # data_only=True: cached values only, formulas are never evaluated.
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:  # openpyxl raises many types for malformed files
            raise ReadError("The workbook could not be read.") from exc
        try:
            sheets = list(wb.sheetnames)
            name = sheet or sheets[0]
            if name not in sheets:
                raise ReadError(f"Sheet '{name}' not found.")
            all_rows = list(wb[name].iter_rows(values_only=True))
        finally:
            wb.close()
        if len(all_rows) < header_row:
            raise ReadError("The sheet has no header row.")
        return _build(list(all_rows[header_row - 1]), [list(r) for r in all_rows[header_row:]], header_row + 1, sheets)

    raise ReadError(f"Unsupported file type {file_type}.")
