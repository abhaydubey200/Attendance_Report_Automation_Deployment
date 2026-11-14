import type { NavPage } from "../api/types";
import { Notice, PageHeader } from "../components/ui";

export function PlaceholderPage({ page }: { page: NavPage }) {
  return (
    <>
      <PageHeader title={page.title} subtitle={page.section} />
      <Notice>Planned for Phase {page.phase}. This page is not available yet.</Notice>
    </>
  );
}

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not available" />
      <Notice kind="warn">This page does not exist or you do not have access to it.</Notice>
    </>
  );
}
