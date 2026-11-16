"""The APIS logo used on every email, dashboard and Excel report (always centred, no company text next to it)."""
from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"
LOGO_CID = "apis-logo"                      # emails reference the logo as <img src="cid:apis-logo">
LOGO_SRC = f"cid:{LOGO_CID}"


@lru_cache(maxsize=None)
def logo_png(small: bool = False) -> bytes:
    """360 px wide PNG (shown at 150 px in emails, sharp on high-DPI screens); small = 160 px for Excel."""
    return (ASSETS / ("apis_logo_small.png" if small else "apis_logo.png")).read_bytes()


def logo_data_uri() -> str:
    """For files opened in a browser (dashboard, in-app email preview), where cid: links do not resolve."""
    return "data:image/png;base64," + base64.b64encode(logo_png()).decode("ascii")


def inline_logo_for_browser(html: str) -> str:
    return html.replace(LOGO_SRC, logo_data_uri())


def excel_banner(wb, ws, widths: list[float], title: str, subtitle: str | None = None, *, max_px: int = 900) -> None:
    """Centred logo in row 0, centred title in row 1 (and subtitle in row 2) of an xlsxwriter sheet.
    widths = the sheet's column widths (characters); the logo is centred over them (capped at max_px)."""
    import io

    px = [int(w * 7 + 5) for w in widths]
    span, last = 0, 0
    for i, w in enumerate(px):                      # columns the banner spans (up to max_px wide)
        if span and span + w > max_px:
            break
        span, last = span + w, i
    ws.set_row(0, 54)
    img_w = 120                                     # 160 px PNG at 75 %
    ws.insert_image(0, 0, "apis_logo.png", {"image_data": io.BytesIO(logo_png(small=True)), "x_scale": 0.75, "y_scale": 0.75,
                                            "x_offset": max(0, (span - img_w) // 2), "y_offset": 4, "object_position": 3})
    t = wb.add_format({"bold": True, "font_size": 15, "font_color": "#5E3C0F", "align": "center", "valign": "vcenter"})
    s = wb.add_format({"italic": True, "font_color": "#6E6152", "align": "center"})
    for row, text, fmt in ((1, title, t), (2, subtitle, s)):
        if text is None:
            continue
        if last > 0:
            ws.merge_range(row, 0, row, last, text, fmt)
        else:
            ws.write(row, 0, text, fmt)
