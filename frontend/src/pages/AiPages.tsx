import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import type { AskResult, RunInfo } from "../api/types";
import { Card, DataTable, ErrorNotice, Loading, Notice, PageHeader, StatusBadge } from "../components/ui";
import { formatDate } from "../format";

interface SummaryResponse {
  run: RunInfo | null;
  summary: { status: string; text: string | null; model: string | null; prompt_version: string; created_at: string } | null;
  note?: string;
}

export function AiSummaryPage() {
  const status = useApi<{ enabled: boolean; model: string | null }>("/v1/ai/status");
  const data = useApi<SummaryResponse>("/v1/ai/summary");
  return (
    <>
      <PageHeader title="Executive Summary" subtitle="Optional AI commentary built only from validated, aggregated metrics" />
      {status.data && !status.data.enabled && (
        <Notice kind="warn">AI is switched off (config/ai_config.yaml). Reports and figures are unaffected; commentary appears here once a model is approved and enabled.</Notice>
      )}
      {data.loading && <Loading />}
      {data.error && <ErrorNotice error={data.error} />}
      {data.data?.note && <Notice>{data.data.note}</Notice>}
      {data.data?.run && (
        <Card title={`Run ${data.data.run.run_ref} — ${formatDate(data.data.run.reporting_date)}`}>
          {data.data.summary?.text ? (
            <>
              <p className="ai-text">{data.data.summary.text}</p>
              <p className="muted small">Model {data.data.summary.model} · prompt {data.data.summary.prompt_version} · AI never changes official figures.</p>
            </>
          ) : (
            <p className="muted">No AI commentary for this run (status: <StatusBadge value={data.data.summary?.status ?? data.data.run.ai_status ?? "UNAVAILABLE"} />).</p>
          )}
        </Card>
      )}
    </>
  );
}

interface Turn { q: string; a: AskResult }

export function AnalystPage() {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const act = useAction();

  async function ask(e?: FormEvent, q = question) {
    e?.preventDefault();
    if (!q.trim()) return;
    const a = await act.run(() => api.post<AskResult>("/v1/ai/ask", { question: q }));
    if (a) {
      setTurns([{ q, a }, ...turns]);
      setQuestion("");
    }
  }

  const suggestions = turns[0]?.a.supported_questions ?? [
    "What was yesterday's overall attendance?", "Which department had the highest absenteeism?", "Show employees with missing punches.",
    "Compare the last two reporting periods.", "Which source has the most unresolved attendance conflicts?", "Explain the department-wise attendance trend.",
  ];

  return (
    <>
      <PageHeader title="Attendance Analyst" subtitle="Ask about attendance. Answers come from approved, read-only queries within your access." />
      <Card>
        <form className="ask-form" onSubmit={ask}>
          <input value={question} maxLength={300} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. Which department had the highest absenteeism on 13-11-2026?" />
          <button className="btn btn-primary btn-inline" disabled={act.busy}>{act.busy ? "Asking…" : "Ask"}</button>
        </form>
        <div className="chips">
          {suggestions.map((s) => <button key={s} type="button" className="chip" onClick={() => void ask(undefined, s)}>{s}</button>)}
        </div>
        {act.error && <Notice kind="fail">{act.error}</Notice>}
      </Card>
      {turns.map((t, i) => (
        <Card key={i} title={t.q}>
          <p className="ai-text">{t.a.text}</p>
          {t.a.table && t.a.table.rows.length > 0 && (
            <DataTable rows={t.a.table.rows} rowKey={(r) => JSON.stringify(r)}
              columns={t.a.table.header.map((h, idx) => ({ header: h, render: (r: (string | number | null)[]) => r[idx] ?? "" }))} />
          )}
          {t.a.source && <p className="muted small">Source: {t.a.source} · Period: {t.a.period ? formatDate(t.a.period) : "—"}{t.a.phrased_by_ai ? " · worded by AI" : ""}</p>}
        </Card>
      ))}
    </>
  );
}
