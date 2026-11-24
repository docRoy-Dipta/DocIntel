"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { LogicalPanel } from "@/components/LogicalPanel";
import { PageViewer } from "@/components/PageViewer";
import { Card, ErrorBox, ProgressBar, Spinner, StatusBadge, Timeline } from "@/components/ui";
import {
  ACTIVE_STATUSES, api, apiBlob, type Bbox, type DocStatus, type DocumentRow, type Logical, type PageInfo,
  type Paginated, type ProcEvent,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatBytes, formatDate, formatMoney } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

type Tab = "extraction" | "pages" | "history";

export default function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const [tab, setTab] = useState<Tab>("extraction");
  const [selected, setSelected] = useState<number | null>(null);
  const [focus, setFocus] = useState<{ page: number | null; bbox: Bbox; field: string | null }>({ page: null, bbox: null, field: null });
  const [message, setMessage] = useState<string | null>(null);

  const doc = useAsync(() => api<DocumentRow>(`/documents/${id}`), [id]);
  const status = useAsync(() => api<DocStatus>(`/documents/${id}/status`), [id], (s) => (s && ACTIVE_STATUSES.includes(s.status) ? 1500 : null));
  const done = status.data !== null && !ACTIVE_STATUSES.includes(status.data.status);
  const logicals = useAsync(() => api<Logical[]>(`/documents/${id}/extractions`), [id, done ? status.data?.status : "active"]);

  // when processing finishes, refresh the document row once
  useEffect(() => {
    if (done) void doc.reload();
  }, [done]); // eslint-disable-line react-hooks/exhaustive-deps

  const list = logicals.data ?? [];
  const current = list.find((l) => l.id === selected) ?? list.find((l) => l.doc_type !== "other") ?? list[0] ?? null;
  const previewPage = focus.page ?? current?.start_page ?? 1;

  async function reprocess(mode: "resume" | "reextract") {
    setMessage(null);
    try {
      await api(`/documents/${id}/reprocess`, { method: "POST", json: { mode } });
      setMessage(mode === "resume" ? "Retrying failed work…" : "Re-extracting (your corrections are kept)…");
      await status.reload();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not reprocess");
    }
  }

  async function download() {
    const blob = await apiBlob(`/documents/${id}/file?download=true`);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = doc.data?.original_filename ?? "document";
    a.click();
    URL.revokeObjectURL(url);
  }

  if (doc.loading && !doc.data) return <Spinner />;
  if (!doc.data) return <ErrorBox message={doc.error ?? "Document not found"} />;
  const d = doc.data;
  const st = status.data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/documents" className="text-sm text-slate-500 hover:underline">← Documents</Link>
        <h1 className="text-xl font-semibold">{d.original_filename}</h1>
        <StatusBadge status={st?.status ?? d.status} />
        <span className="text-sm text-slate-500">{d.kind.toUpperCase()} · {formatBytes(d.size_bytes)} · {d.page_count} page(s) · uploaded {formatDate(d.created_at)}</span>
        <div className="ml-auto flex gap-2">
          <button className="btn-secondary" onClick={download}>Download original</button>
          {can("reviewer") && done && (
            <>
              <button className="btn-secondary" onClick={() => reprocess("resume")}>Retry failed</button>
              <button className="btn-secondary" onClick={() => reprocess("reextract")}>Re-extract</button>
            </>
          )}
        </div>
      </div>
      {message && <p className="rounded-lg bg-slate-100 px-3 py-2 text-sm">{message}</p>}
      {(st?.error_message ?? d.error_message) && <ErrorBox message={st?.error_message ?? d.error_message} />}
      {st && !done && (
        <Card title="Processing…">
          <ProgressBar value={st.progress} />
          <p className="pt-1 text-xs text-slate-500">{st.pages_done}/{st.page_count} pages · {st.extractions_done}/{st.logical_documents} extractions</p>
        </Card>
      )}

      <div className="flex gap-1 border-b border-slate-200">
        {(["extraction", "pages", "history"] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium capitalize ${tab === t ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-700"}`}>{t}</button>
        ))}
      </div>

      {tab === "extraction" && (
        <>
          {list.length > 1 && (
            <div className="flex flex-wrap gap-2">
              {list.map((l) => (
                <button
                  key={l.id}
                  onClick={() => { setSelected(l.id); setFocus({ page: null, bbox: null, field: null }); }}
                  className={`rounded-lg border px-3 py-1.5 text-left text-xs ${current?.id === l.id ? "border-indigo-500 bg-indigo-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}
                >
                  <div className="font-medium">{l.doc_type} · p.{l.start_page}{l.end_page !== l.start_page ? `–${l.end_page}` : ""}</div>
                  <div className="text-slate-500">{l.fields.find((f) => f.name === "invoice_number")?.value ?? "—"} · {formatMoney(l.fields.find((f) => f.name === "total_amount")?.value)}</div>
                  {l.needs_review && <span className="text-amber-700">needs review</span>}
                </button>
              ))}
            </div>
          )}
          {logicals.loading && !logicals.data && <Spinner />}
          {!current && !logicals.loading && <p className="text-sm text-slate-500">No documents were found in this file yet.</p>}
          {current && current.doc_type === "other" && <Card><p className="text-sm text-slate-600">These pages were classified as “other” (not an invoice or receipt), so nothing was extracted.</p></Card>}
          {current && current.doc_type !== "other" && (
            <div className="grid gap-4 lg:grid-cols-2">
              <Card title={`Preview${previewPage ? ` — page ${previewPage}` : ""}`}>
                <div className="mb-2 flex flex-wrap gap-1">
                  {Array.from({ length: current.end_page - current.start_page + 1 }, (_, i) => current.start_page + i).slice(0, 30).map((p) => (
                    <button key={p} onClick={() => setFocus({ page: p, bbox: null, field: null })} className={`rounded px-2 py-0.5 text-xs ${p === previewPage ? "bg-indigo-600 text-white" : "bg-slate-100 hover:bg-slate-200"}`}>{p}</button>
                  ))}
                </div>
                <PageViewer docId={id} kind={d.kind} page={previewPage} highlight={focus.bbox} />
              </Card>
              <Card title={`${current.doc_type} · pages ${current.start_page}–${current.end_page}`}>
                <LogicalPanel
                  logical={current}
                  selectedField={focus.field}
                  onSelect={(page, bbox) => setFocus({ page: page ?? current.start_page, bbox, field: null })}
                  onChange={(u) => { logicals.setData(list.map((l) => (l.id === u.id ? u : l))); void status.reload(); }}
                />
              </Card>
            </div>
          )}
        </>
      )}
      {tab === "pages" && <PagesTab id={id} />}
      {tab === "history" && <HistoryTab id={id} live={!done} />}
    </div>
  );
}

function PagesTab({ id }: { id: string }) {
  const pages = useAsync(() => api<Paginated<PageInfo>>(`/documents/${id}/pages?size=200`), [id]);
  if (pages.loading) return <Spinner />;
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-200">
        <thead className="bg-slate-50"><tr><th className="th">Page</th><th className="th">Status</th><th className="th">Method</th><th className="th">OCR confidence</th><th className="th">Characters</th><th className="th">Note</th></tr></thead>
        <tbody className="divide-y divide-slate-100">
          {pages.data?.items.map((p) => (
            <tr key={p.page_number}>
              <td className="td">{p.label ?? p.page_number}</td>
              <td className="td"><StatusBadge status={p.status} /></td>
              <td className="td">{p.method ?? "—"}</td>
              <td className="td">{p.ocr_confidence === null ? "—" : `${Math.round(p.ocr_confidence * 100)}%`}</td>
              <td className="td tabular-nums">{p.char_count}</td>
              <td className="td text-rose-600">{p.error}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {pages.data && pages.data.total > 200 && <p className="p-3 text-xs text-slate-500">Showing the first 200 of {pages.data.total} pages.</p>}
    </div>
  );
}

function HistoryTab({ id, live }: { id: string; live: boolean }) {
  const events = useAsync(() => api<ProcEvent[]>(`/documents/${id}/history`), [id], live ? 2000 : null);
  if (events.loading && !events.data) return <Spinner />;
  return <Card title="Processing history"><Timeline events={events.data ?? []} /></Card>;
}
