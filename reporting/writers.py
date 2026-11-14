"""XLSX (XlsxWriter) and HTML (Jinja2) renderers in the APIS look. Every report carries
its period, generation time, run, data freshness, rule version and report version, and
a PROVISIONAL banner while HR rules are unapproved (PRD 11.5)."""

from __future__ import annotations

import io

import xlsxwriter
from jinja2 import Environment, PackageLoader, select_autoescape

BROWN, HONEY, CREAM, INK = "#835415", "#F5B800", "#FFF4E3", "#2B2118"

_env = Environment(loader=PackageLoader("reporting", "templates"), autoescape=select_autoescape(["html"]))


def to_xlsx(data: dict, meta: list[tuple[str, str]]) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    title = wb.add_format({"bold": True, "font_size": 15, "font_color": BROWN})
    meta_key = wb.add_format({"bold": True, "font_color": INK, "bg_color": CREAM})
    banner = wb.add_format({"bold": True, "font_color": "#8A5A00", "bg_color": "#FFF1D6", "border": 1})
    head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": BROWN, "border": 1, "text_wrap": True})
    cell = wb.add_format({"border": 1, "border_color": "#ECDFC9", "valign": "top"})
    for sheet_name, header, rows in data["sheets"]:
        ws = wb.add_worksheet(sheet_name[:31])
        ws.write(0, 0, data["title"], title)
        r = 1
        for k, v in meta:
            ws.write(r, 0, k, meta_key)
            ws.write(r, 1, v)
            r += 1
        if data["provisional"]:
            ws.merge_range(r, 0, r, max(len(header) - 1, 3),
                           "PROVISIONAL - attendance rules are not yet approved by HR; figures are subject to change.", banner)
            r += 1
        r += 1
        for c, h in enumerate(header):
            ws.write(r, c, h, head)
        for i, row in enumerate(rows, start=r + 1):
            for c, v in enumerate(row):
                ws.write(i, c, v, cell)
        if not rows:
            ws.write(r + 1, 0, "No records.", cell)
        ws.freeze_panes(r + 1, 0)
        if rows:
            ws.autofilter(r, 0, r + len(rows), len(header) - 1)
        for c, h in enumerate(header):
            width = max([len(str(h))] + [len(str(row[c])) for row in rows[:500] if c < len(row)]) + 2
            ws.set_column(c, c, min(max(width, 10), 60))
        ws.set_column(0, 0, max(28, min(60, max([len(k) for k, _ in meta] + [10]) + 2)))
    wb.close()
    return buf.getvalue()


def to_html(data: dict, meta: list[tuple[str, str]]) -> bytes:
    return _env.get_template("report.html").render(data=data, meta=meta).encode("utf-8")
