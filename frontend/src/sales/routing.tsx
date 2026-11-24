// Sales routing: who reports to whom and where each person's daily email goes (the approved APIS Sales Dashboard, from live data).
import { useMemo, useState } from "react";
import { useApi } from "../api/useApi";
import { Card, DataTable, ErrorNotice, KpiCard, Loading, Notice, PageHeader } from "../components/ui";

interface RoutingRow { code: string; name: string; role: string; department: string; doj: string; hod: string; hod_email: string;
  manager: string; territory: string; goes_to: string; check: string; issue: string }
interface RoutingData { rows: RoutingRow[]; excluded: { code: string; name: string }[]; emails_per_day: number; hr_exception_day: boolean;
  exceptions: { code: string; name: string; issue: string; detail: string }[] }

type Key = "hod" | "manager" | "territory" | "role" | "department" | "check";
const LABEL: Record<Key, string> = { hod: "HOD", manager: "Reporting manager", territory: "Territory (GTR)", role: "Role", department: "Department", check: "Data check" };
const ALL: Record<Key, string> = { hod: "All HODs", manager: "All reporting managers", territory: "All territories", role: "All roles", department: "All departments", check: "All records" };
const KEYS = Object.keys(LABEL) as Key[];

export function SalesRoutingPage() {
  const d = useApi<RoutingData>("/v1/sales/routing");
  const [f, setF] = useState<Record<Key, string>>({ hod: "", manager: "", territory: "", role: "", department: "", check: "" });
  const [q, setQ] = useState("");
  const R = d.data?.rows ?? [];
  const match = (r: RoutingRow, skip?: Key) => (!q || [r.name, r.code, r.goes_to].some((x) => x.toLowerCase().includes(q.toLowerCase())))
    && KEYS.every((k) => k === skip || !f[k] || r[k] === f[k]);
  const rows = useMemo(() => R.filter((r) => match(r)), [R, f, q]);   // eslint-disable-line react-hooks/exhaustive-deps
  const count = (list: RoutingRow[], k: Key) => list.reduce<Record<string, number>>((o, r) => { o[r[k]] = (o[r[k]] ?? 0) + 1; return o; }, {});
  const set = (k: Key, v: string) => setF((s) => ({ ...s, [k]: v, ...(k === "hod" ? { manager: "" } : {}) }));
  if (d.loading) return <Loading />;
  if (d.error) return <ErrorNotice error={d.error} />;
  const hods = count(R, "hod"), hodShown = count(R.filter((r) => match(r, "hod")), "hod");
  const mgrShown = count(R.filter((r) => match(r, "manager")), "manager");
  const mgrInfo = R.reduce<Record<string, { t: Set<string>; e: string }>>((o, r) => { (o[r.manager] ??= { t: new Set(), e: r.goes_to }).t.add(r.territory); return o; }, {});
  const hodEmail = Object.fromEntries(R.map((r) => [r.hod, r.hod_email]));
  const chips = KEYS.filter((k) => f[k]);
  return (
    <>
      <PageHeader title="Sales routing" subtitle="General Trade and Alternate Channels · pick a filter or click a HOD or manager to see who reports where and who gets each daily email" />
      <Card title="How the sales team is organised">
        <div className="rt-flow"><b>Amit Anand</b><i>→</i><b>Arun Mishra (HOD, General Trade)</b><i>→</i><b>Managers by territory GTR01–GTR09</b><i>→</i><b>their team members</b></div>
        <div className="rt-flow"><b>Amit Anand</b><i>→</i><b>Vaibhav Mishra (HOD, Alternate Channels)</b><i>→</i><b>Gouri Shankar (East, West, North, South)</b><i>→</i><b>team members</b></div>
        {d.data && d.data.excluded.length > 0 && <p className="muted small">Not in this run (reported in the Head Office run): {d.data.excluded.map((x) => `${x.name} (${x.code})`).join(", ")}.</p>}
      </Card>
      <Card>
        <div className="rt-filters">
          <label>Search employee<input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, code or email" /></label>
          {KEYS.map((k) => { const c = count(R.filter((r) => match(r, k)), k);
            return <label key={k}>{LABEL[k]}<select value={f[k]} onChange={(e) => set(k, e.target.value)}>
              <option value="">{ALL[k]}</option>{Object.keys(c).sort().map((v) => <option key={v} value={v}>{v || "—"} ({c[v]})</option>)}</select></label>; })}
          <button type="button" className="btn btn-primary btn-small" onClick={() => { setF({ hod: "", manager: "", territory: "", role: "", department: "", check: "" }); setQ(""); }}>Clear all filters</button>
        </div>
        <div className="rt-chips">
          {chips.map((k) => <button key={k} type="button" className="rt-chip" onClick={() => set(k, "")}>{LABEL[k]}: {f[k]} ✕</button>)}
          {q && <button type="button" className="rt-chip" onClick={() => setQ("")}>Search: {q} ✕</button>}
        </div>
      </Card>
      <div className="kpi-grid">
        <KpiCard label="Employees shown" value={rows.length} tone="brand" hint={`${R.length} in scope`} />
        <KpiCard label="Managers" value={Object.keys(count(rows, "manager")).length} />
        <KpiCard label="Territories" value={Object.keys(count(rows, "territory")).length} />
        <KpiCard label="Attendance emails per day" value={d.data?.emails_per_day ?? "–"} tone="info"
          hint={d.data?.hr_exception_day ? "managers, HODs and Director – plus HR while there are exceptions" : "managers, HODs and Director"} />
      </div>
      {d.data && d.data.exceptions.length > 0 && (
        <Notice kind="warn">Needs checking by HR: {d.data.exceptions.map((x) => `${x.name || x.code} – ${x.detail}`).join(" · ")}</Notice>
      )}
      <Card title="Heads of Department">
        <p className="muted small">Click a box to filter. Click it again to remove the filter.</p>
        <div className="rt-cards">
          {Object.keys(hods).sort((a, b) => hods[b] - hods[a]).map((h) => { const n = hodShown[h] ?? 0;
            return <button key={h} type="button" className={`rt-card hod${f.hod === h ? " on" : ""}${n ? "" : " dim"}`} onClick={() => set("hod", f.hod === h ? "" : h)}>
              <span className="nm">{h || "—"}</span><span className="ct">{n} employee{n === 1 ? "" : "s"}</span><span className="sm">{hodEmail[h]}</span></button>; })}
        </div>
      </Card>
      <Card title="Reporting managers">
        <p className="muted small">Each manager receives one daily email for the people reporting to them. Click a manager to see only those people.</p>
        <div className="rt-cards">
          {Object.keys(mgrShown).sort((a, b) => mgrShown[b] - mgrShown[a]).map((m) => (
            <button key={m} type="button" className={`rt-card${f.manager === m ? " on" : ""}`} onClick={() => set("manager", f.manager === m ? "" : m)}>
              <span className="nm">{m || "—"}</span><span className="ct">{mgrShown[m]} {mgrShown[m] === 1 ? "person" : "people"}</span>
              <span className="sm">{[...(mgrInfo[m]?.t ?? [])].sort().join(", ")}</span><span className="sm">{mgrInfo[m]?.e}</span></button>))}
        </div>
      </Card>
      <Card title="Employees">
        <DataTable rows={rows} rowKey={(r) => r.code} search exportName="sales_routing" pageSize={100} columns={[
          { header: "Emp code", render: (r) => r.code },
          { header: "Employee", render: (r) => <strong>{r.name}</strong>, value: (r) => r.name },
          { header: "Role", render: (r) => (r.role === "Manager" ? <b>Manager</b> : r.role), value: (r) => r.role },
          { header: "Department", render: (r) => r.department },
          { header: "Date of joining", render: (r) => r.doj },
          { header: "HOD", render: (r) => r.hod },
          { header: "Reports to", render: (r) => r.manager },
          { header: "Territory", render: (r) => r.territory },
          { header: "Daily report goes to", render: (r) => r.goes_to },
          { header: "Data check", render: (r) => <b style={{ color: r.check === "OK" ? "#15803d" : "#b3261e" }}>{r.check}</b>, value: (r) => r.check },
          { header: "Issue", render: (r) => r.issue || "-" },
        ]} />
      </Card>
    </>
  );
}
