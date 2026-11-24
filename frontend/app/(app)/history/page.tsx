"use client";

import Link from "next/link";
import { useState } from "react";
import { Card, ErrorBox, Pagination, Spinner, StatusBadge, Timeline } from "@/components/ui";
import { api, type AuditEntry, type DocumentRow, type Paginated, type ProcEvent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

function DocumentHistory({ doc }: { doc: DocumentRow }) {
  const [open, setOpen] = useState(false);
  const events = useAsync(() => (open ? api<ProcEvent[]>(`/documents/${doc.id}/history`) : Promise.resolve([])), [open, doc.id]);
  return (
    <li className="py-2">
      <button className="flex w-full items-center gap-3 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="w-4 text-slate-400">{open ? "▾" : "▸"}</span>
        <span className="flex-1 truncate font-medium">{doc.original_filename}</span>
        <StatusBadge status={doc.status} />
        <span className="w-44 text-right text-xs text-slate-500">{formatDate(doc.updated_at)}</span>
      </button>
      {open && (
        <div className="ml-7 mt-2 rounded-lg bg-slate-50 p-3">
          {events.loading ? <Spinner /> : <Timeline events={events.data ?? []} />}
          <Link href={`/documents/${doc.id}`} className="mt-2 inline-block text-xs text-indigo-700 hover:underline">Open document →</Link>
        </div>
      )}
    </li>
  );
}

function AuditLog() {
  const [page, setPage] = useState(1);
  const log = useAsync(() => api<AuditEntry[]>(`/audit-log?page=${page}&size=25`), [page]);
  return (
    <Card title="Audit log (admin)">
      {log.loading && !log.data ? <Spinner /> : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">When</th><th className="th">User</th><th className="th">Action</th><th className="th">Entity</th><th className="th">IP</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {log.data?.map((a) => (
                <tr key={a.id}><td className="td text-slate-500">{formatDate(a.created_at)}</td><td className="td">{a.user_id ?? "—"}</td><td className="td font-medium">{a.action}</td><td className="td text-slate-500">{a.entity_type ?? ""} {a.entity_id?.slice(0, 8) ?? ""}</td><td className="td text-slate-500">{a.ip}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pagination page={page} size={25} total={page * 25 + ((log.data?.length ?? 0) === 25 ? 1 : 0)} onChange={setPage} />
    </Card>
  );
}

export default function HistoryPage() {
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const docs = useAsync(() => api<Paginated<DocumentRow>>(`/documents?page=${page}&size=20`), [page]);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Processing history</h1>
      <ErrorBox message={docs.error} />
      <Card title="Documents (click to expand the full processing timeline)">
        {docs.loading && !docs.data ? <Spinner /> : <ul className="divide-y divide-slate-100">{docs.data?.items.map((d) => <DocumentHistory key={d.id} doc={d} />)}</ul>}
        {docs.data && <Pagination page={docs.data.page} size={docs.data.size} total={docs.data.total} onChange={setPage} />}
      </Card>
      {can("admin") && <AuditLog />}
    </div>
  );
}
