import { useEffect, useState } from "react";
import { apiUrl } from "../api/client";
import { useApi, withQuery } from "../api/useApi";
import { Card, ErrorNotice, Field, Loading, Notice, PageHeader } from "../components/ui";

interface TableInfo {
  name: string;
  rows: number;
  columns: number;
  description: string;
}

interface TableList {
  database: string;
  tables: TableInfo[];
}

interface TableRows {
  name: string;
  description: string;
  total: number;
  offset: number;
  limit: number;
  columns: { name: string; type: string; primary_key: boolean; hidden: boolean }[];
  rows: (string | number | boolean | null)[][];
}

const PAGE_SIZES = [25, 50, 100, 200];

function Cell({ value }: { value: string | number | boolean | null }) {
  const [open, setOpen] = useState(false);
  if (value === null) return <span className="muted">null</span>;
  const text = String(value);
  if (text.length <= 80) return <>{text}</>;
  return (
    <button type="button" className={`db-cell ${open ? "open" : ""}`} onClick={() => setOpen(!open)} title={open ? "Click to shorten" : "Click to show all"}>
      {open ? text : `${text.slice(0, 80)}…`}
    </button>
  );
}

/** Read-only view of every table in the application's database. */
export function DatabasePage() {
  const list = useApi<TableList>("/v1/db/tables");
  const [table, setTable] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<string | null>(null);
  const [direction, setDirection] = useState<"asc" | "desc">("asc");
  const [limit, setLimit] = useState(50);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    if (!table && list.data?.tables.length) {
      setTable(list.data.tables.find((t) => t.name.endsWith("employee"))?.name ?? list.data.tables[0].name);
    }
  }, [list.data, table]);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setSearch(q);
      setOffset(0);
    }, 350);
    return () => window.clearTimeout(t);
  }, [q]);

  const params = { q: search, sort, direction: sort ? direction : null };
  const data = useApi<TableRows>(table ? withQuery(`/v1/db/tables/${encodeURIComponent(table)}`, { ...params, limit, offset }) : null);

  function pick(name: string) {
    setTable(name);
    setQ("");
    setSearch("");
    setSort(null);
    setOffset(0);
  }

  function sortBy(col: string) {
    if (sort === col) setDirection(direction === "asc" ? "desc" : "asc");
    else {
      setSort(col);
      setDirection("asc");
    }
    setOffset(0);
  }

  const d = data.data;
  const last = d ? Math.min(d.offset + d.limit, d.total) : 0;

  return (
    <>
      <PageHeader title="Database" subtitle="Everything the application has stored, table by table. Read-only: nothing can be changed here." />
      {list.loading && <Loading />}
      {list.error && <ErrorNotice error={list.error} />}
      {list.data && (
        <div className="db-layout">
          <Card title={`Tables (${list.data.tables.length})`}>
            <div className="db-tables">
              {list.data.tables.map((t) => (
                <button key={t.name} type="button" className={`db-table ${t.name === table ? "on" : ""}`} onClick={() => pick(t.name)} title={t.description}>
                  <span className="db-table-name">{t.name}</span>
                  <span className="db-table-count">{t.rows.toLocaleString("en-IN")}</span>
                  {t.description && <span className="db-table-desc">{t.description}</span>}
                </button>
              ))}
            </div>
            <p className="muted small">Database: {list.data.database}. Passwords and tokens are hidden.</p>
          </Card>

          <div className="db-main">
            {table && (
              <Card
                title={table}
                actions={<a className="btn btn-ghost btn-small" href={apiUrl(`/v1/db/tables/${encodeURIComponent(table)}/csv`, params)}>Download CSV</a>}
              >
                {d?.description && <p className="muted small">{d.description}</p>}
                <div className="db-controls">
                  <Field label="Search all columns">
                    <input type="search" value={q} placeholder="Type to search…" onChange={(e) => setQ(e.target.value)} />
                  </Field>
                  <Field label="Rows per page">
                    <select value={limit} onChange={(e) => { setLimit(Number(e.target.value)); setOffset(0); }}>
                      {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </Field>
                  {d && (
                    <div className="db-pager">
                      <span className="muted small">{d.total ? `${(d.offset + 1).toLocaleString("en-IN")}–${last.toLocaleString("en-IN")} of ${d.total.toLocaleString("en-IN")}` : "0 rows"}</span>
                      <button type="button" className="btn btn-ghost btn-small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>‹ Previous</button>
                      <button type="button" className="btn btn-ghost btn-small" disabled={last >= d.total} onClick={() => setOffset(offset + limit)}>Next ›</button>
                    </div>
                  )}
                </div>
                {data.loading && <Loading />}
                {data.error && <ErrorNotice error={data.error} />}
                {d && d.rows.length === 0 && !data.loading && <Notice>{search ? "No rows match this search." : "This table is empty."}</Notice>}
                {d && d.rows.length > 0 && (
                  <div className="table-wrap db-wrap">
                    <table className="data-table db-grid">
                      <thead>
                        <tr>
                          {d.columns.map((c) => (
                            <th key={c.name} title={`${c.type}${c.primary_key ? " · primary key" : ""}`}>
                              <button type="button" className="db-sort" onClick={() => sortBy(c.name)}>
                                {c.name}
                                {sort === c.name ? (direction === "asc" ? " ▲" : " ▼") : ""}
                              </button>
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {d.rows.map((r, i) => (
                          <tr key={`${d.offset}-${i}`}>
                            {r.map((v, j) => <td key={d.columns[j].name}><Cell value={v} /></td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            )}
          </div>
        </div>
      )}
    </>
  );
}
