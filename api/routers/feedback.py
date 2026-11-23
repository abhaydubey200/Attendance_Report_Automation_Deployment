"""'Was this right?' pages for the Field Sales email links (no sign-in: the link itself is signed and expires).
Outside /api on purpose: a plain HTML form cannot send the API's request header. Opening the link only shows a confirm
page; the answer is saved by the button (POST), so mail scanners that open links do not answer for the HOD."""

from __future__ import annotations

import html

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from api.deps import get_db

router = APIRouter(tags=["feedback"])

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HR Portal</title><style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f6f7fb;color:#14213d;margin:0;padding:40px 16px}}
.c{{max-width:460px;margin:auto;background:#fff;border:1px solid #e6e8ef;border-radius:14px;padding:24px}}
button{{background:#14213d;color:#fff;border:0;border-radius:10px;padding:10px 18px;font-size:15px;cursor:pointer}}
p{{line-height:1.5}}</style></head><body><div class="c"><h2 style="margin-top:0">HR Portal · Field Sales</h2>{body}</div></body></html>"""


def _page(body: str, code: int = 200) -> HTMLResponse:
    return HTMLResponse(_PAGE.format(body=body), status_code=code,
                        headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
                                 "Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


@router.get("/feedback/sales/{tok}/{answer}", include_in_schema=False)
def ask(tok: str, answer: str) -> HTMLResponse:
    from sales import feedback
    got = feedback.read(tok)
    if got is None or answer not in feedback.ANSWERS:
        return _page("<p>This link is not valid any more (links work for 3 weeks).</p>", 404)
    code, day, _ = got
    label = feedback.ANSWERS[answer][2]
    return _page(f"<p>Your answer for <b>{html.escape(code)}</b> on <b>{day:%d-%b-%Y}</b>:</p><p><b>{html.escape(label)}</b></p>"
                 f"<form method='post'><button type='submit'>Confirm</button></form>")


@router.post("/feedback/sales/{tok}/{answer}", include_in_schema=False)
def save(tok: str, answer: str, db: Session = Depends(get_db)) -> HTMLResponse:
    from sales import feedback
    ok, msg = feedback.record(db, tok, answer)
    return _page(f"<p>{html.escape(msg)}</p>", 200 if ok else 400)
