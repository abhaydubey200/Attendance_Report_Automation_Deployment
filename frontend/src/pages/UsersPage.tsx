import { useApi } from "../api/useApi";
import type { RoleRow, UserRow } from "../api/types";
import { Badge, DataTable, ErrorNotice, Loading, PageHeader } from "../components/ui";
import { formatDateTime } from "../format";

export function UsersPage() {
  const users = useApi<UserRow[]>("/v1/admin/users");
  const roles = useApi<RoleRow[]>("/v1/admin/roles");

  return (
    <>
      <PageHeader title="Users and Roles" subtitle={<>Create users with <code>python main.py create-user</code></>} />
      {users.loading && <Loading />}
      {users.error && <ErrorNotice error={users.error} />}
      {users.data && (
        <DataTable rows={users.data} rowKey={(u) => String(u.user_id)}
          columns={[
            { header: "Username", render: (u) => u.username },
            { header: "Name", render: (u) => u.display_name },
            { header: "Roles", render: (u) => u.roles.join(", ") },
            { header: "Departments", render: (u) => u.departments.join(", ") || "—" },
            { header: "Status", render: (u) => <Badge kind={u.is_active ? "ok" : "fail"}>{u.is_active ? "Active" : "Inactive"}</Badge> },
            { header: "Last login", render: (u) => formatDateTime(u.last_login_at) },
          ]} />
      )}

      <h2>Role permissions</h2>
      {roles.data && (
        <DataTable rows={roles.data} rowKey={(r) => r.role}
          columns={[
            { header: "Role", render: (r) => <strong>{r.role}</strong> },
            { header: "Description", render: (r) => r.description },
            { header: "Permissions", render: (r) => <span className="perm-list">{r.permissions.join(", ")}</span> },
          ]} />
      )}
    </>
  );
}
