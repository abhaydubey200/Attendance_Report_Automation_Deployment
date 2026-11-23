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


def read_raw(data: bytes, file_type: str, sheet: str | None = None) -> tuple[list[list[str]], list[str]]:
    """All rows as lists of strings (no header interpretation), plus sheet names."""
    if file_type == "csv":
        text = _decode(data)
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;	|")
        except csv.Error:
            dialect = csv.excel
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect)]
        sheets: list[str] = []
    elif file_type == "xlsx":
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
            rows = [[_cell_to_str(v) for v in r] for r in wb[name].iter_rows(values_only=True)]
        finally:
            wb.close()
    elif file_type == "html":
        rows, sheets = _html_rows(_decode(data)), []
    else:
        raise ReadError(f"Unsupported file type {file_type}.")
    if len(rows) > MAX_ROWS + 50:
        raise ReadError(f"The file has more than {MAX_ROWS:,} rows.")
    return rows, sheets


def read_table(data: bytes, file_type: str, sheet: str | None = None, header_row: int = 1) -> Table:
    if header_row < 1:
        raise ReadError("Header row must be 1 or more.")
    rows, sheets = read_raw(data, file_type, sheet)
    if len(rows) < header_row:
        raise ReadError("The file has no header row.")
    return _build(rows[header_row - 1], rows[header_row:], header_row + 1, sheets)


def read_for_dataset(data: bytes, file_type: str, dataset_id: str, sheet: str | None = None, header_row: int = 1) -> Table:
    """Use the dataset's report-specific reshaper when it has one (header found automatically)."""
    from ingestion.reshapers import RESHAPERS

    reshaper = RESHAPERS.get(dataset_id)
    if reshaper is None:
        return read_table(data, file_type, sheet, header_row)
    rows, sheets = read_raw(data, file_type, sheet)
    return reshaper(rows, 1, sheets)


def _html_rows(text: str) -> list[list[str]]:
    """The rows of every <table> in an HTML report saved as .xls (Pocket HRMS). Only cell text is kept: tags,
    scripts and styles are dropped, nothing is executed or fetched."""
    from html.parser import HTMLParser

    class _Rows(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.rows: list[list[str]] = []
            self.row: list[str] | None = None
            self.cell: list[str] | None = None
            self.skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self.skip += 1
            elif tag == "tr":
                self._end_row()
                self.row = []
            elif tag in ("td", "th"):
                self._end_cell()
                if self.row is None:
                    self.row = []
                self.cell = []
            elif tag == "br" and self.cell is not None:
                self.cell.append(" ")

        def handle_endtag(self, tag):
            if tag in ("script", "style"):
                self.skip = max(0, self.skip - 1)
            elif tag in ("td", "th"):
                self._end_cell()
            elif tag == "tr":
                self._end_row()

        def handle_data(self, data):
            if self.cell is not None and not self.skip:
                self.cell.append(data)

        def _end_cell(self):
            if self.cell is not None and self.row is not None:
                self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None

        def _end_row(self):
            self._end_cell()
            if self.row is not None:
                self.rows.append(self.row)
            self.row = None

    parser = _Rows()
    parser.feed(text)
    parser.close()
    parser._end_row()
    return parser.rows
