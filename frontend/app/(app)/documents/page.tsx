"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ErrorBox, Pagination, ProgressBar, Spinner, StatusBadge } from "@/components/ui";
import { ACTIVE_STATUSES, api, type DocumentRow, type Paginated } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatBytes, formatDate } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

const STATUS_OPTIONS = ["", "queued", "processing", "analyzing", "completed", "needs_review", "failed", "rejected"];

function DocumentsInner() {
  const params = useSearchParams();
  const router = useRouter();
  const { can } = useAuth();
  const status = params.get("status") ?? "";
  const [q, setQ] = useState(params.get("q") ?? "");
  const [page, setPage] = useState(1);
  const [picked, setPicked] = useState<string[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  const list = useAsync(
    () => api<Paginated<DocumentRow>>(`/documents?page=${page}&size=25${status ? `&status=${status}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`),
    [page, status, q],
    (d) => (d?.items.some((x) => ACTIVE_STATUSES.includes(x.status)) ? 2500 : null),
  );

  async function retryFailed() {
    try {
      const r = await api<{ requeued: number }>("/documents/reprocess-failed", { method: "POST" });
      setMessage(`Re-queued ${r.requeued} document(s).`);
      void list.reload();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Failed");
    }
  }

  const togglePick = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-2)));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-xl font-semibold">Documents</h1>
        <input className="input w-56" placeholder="Search file name…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <select className="input w-44" value={status} onChange={(e) => { router.push(e.target.value ? `/documents?status=${e.target.value}` : "/documents"); setPage(1); }}>
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s ? s.replaceAll("_", " ") : "All statuses"}</option>)}
        </select>
        {can("reviewer") && <button className="btn-secondary" onClick={retryFailed}>Retry all failed</button>}
        <button className="btn-primary" disabled={picked.length !== 2} onClick={() => router.push(`/compare?left=${picked[0]}&right=${picked[1]}`)}>
          Compare selected ({picked.length}/2)
        </button>
      </div>
      {message && <p className="rounded-lg bg-slate-100 px-3 py-2 text-sm">{message}</p>}
      <ErrorBox message={list.error} />
      {list.loading && !list.data ? <Spinner /> : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr><th className="th w-8" /><th className="th">File</th><th className="th">Status</th><th className="th">Pages</th><th className="th">Invoices</th><th className="th">To review</th><th className="th">Size</th><th className="th">Uploaded</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {list.data?.items.map((d) => (
                <tr key={d.id} className="hover:bg-slate-50">
                  <td className="td"><input type="checkbox" aria-label={`Select ${d.original_filename}`} checked={picked.includes(d.id)} onChange={() => togglePick(d.id)} /></td>
                  <td className="td"><Link className="font-medium text-indigo-700 hover:underline" href={`/documents/${d.id}`}>{d.original_filename}</Link><div className="text-xs uppercase text-slate-400">{d.kind}</div></td>
                  <td className="td">
                    <StatusBadge status={d.status} />
                    {ACTIVE_STATUSES.includes(d.status) && d.page_count > 0 && <div className="mt-1 w-24"><ProgressBar value={d.pages_done / d.page_count} /></div>}
                  </td>
                  <td className="td tabular-nums">{d.pages_done}/{d.page_count}</td>
                  <td className="td tabular-nums">{d.invoices ?? 0}</td>
                  <td className="td tabular-nums">{d.needs_review ? <span className="font-medium text-amber-700">{d.needs_review}</span> : 0}</td>
                  <td className="td text-slate-500">{formatBytes(d.size_bytes)}</td>
                  <td className="td text-slate-500">{formatDate(d.created_at)}</td>
                </tr>
              ))}
              {list.data?.items.length === 0 && <tr><td className="td py-8 text-center text-slate-500" colSpan={8}>No documents match.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {list.data && <Pagination page={list.data.page} size={list.data.size} total={list.data.total} onChange={setPage} />}
    </div>
  );
}

export default function DocumentsPage() {
  return <Suspense fallback={<Spinner />}><DocumentsInner /></Suspense>;
}
