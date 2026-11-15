"""The four screens of the tool, shown only to users with the permission."""

from __future__ import annotations

from dataclasses import dataclass

from security.authorization import has_permission
from security.permissions import Perm, Principal


@dataclass(frozen=True)
class PageSpec:
    section: str
    title: str
    slug: str
    permission: Perm
    implemented: bool = True
    phase: int | None = None


PAGES: tuple[PageSpec, ...] = (
    PageSpec("Daily attendance", "Upload", "upload", Perm.UPLOAD_AND_SEND),
    PageSpec("Daily attendance", "Insights", "insights", Perm.VIEW_INSIGHTS),
    PageSpec("Daily attendance", "Emails", "emails", Perm.VIEW_INSIGHTS),
    PageSpec("Setup", "Settings", "settings", Perm.MANAGE_SETTINGS),
)


def visible_pages(principal: Principal | None) -> list[PageSpec]:
    return [p for p in PAGES if has_permission(principal, p.permission)]
