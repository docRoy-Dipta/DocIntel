"use client";

import Link from "next/link";
import { Card, ErrorBox, Spinner, StatusBadge } from "@/components/ui";
import { api, type Dashboard } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { percent } from "@/lib/format";

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="card">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

export default function DashboardPage() {
  const { data, error, loading } = useAsync(() => api<Dashboard>("/stats/dashboard"), [], 5000);
  if (loading && !data) return <Spinner />;
  if (!data) return <ErrorBox message={error} />;
  const statuses = Object.entries(data.by_status).filter(([, n]) => n > 0);
  const max = Math.max(1, ...statuses.map(([, n]) => n));

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Documents" value={data.documents_total} hint={`${data.uploads_last_7_days} in the last 7 days`} />
        <Stat label="Awaiting review" value={data.review_queue} hint="invoices needing a human" />
        <Stat label="Success rate" value={percent(data.success_rate)} hint="finished without failure" />
        <Stat label="Failure rate" value={percent(data.failure_rate)} hint="failed or rejected" />
        <Stat label="Pages processed" value={data.pages_processed} hint={`${data.pages_ocr} needed OCR`} />
        <Stat label="Avg. processing time" value={data.avg_processing_seconds === null ? "—" : `${data.avg_processing_seconds.toFixed(1)} s`} hint="upload → final status" />
        <Stat label="Invoices" value={data.logical_documents_by_type.invoice ?? 0} />
        <Stat label="Receipts" value={data.logical_documents_by_type.receipt ?? 0} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Documents by status">
          {statuses.length === 0 ? (
            <p className="text-sm text-slate-500">Nothing uploaded yet. <Link className="text-indigo-600 underline" href="/upload">Upload documents</Link></p>
          ) : (
            <ul className="space-y-2">
              {statuses.map(([status, n]) => (
                <li key={status} className="flex items-center gap-3">
                  <Link href={`/documents?status=${status}`} className="w-32"><StatusBadge status={status} /></Link>
                  <div className="h-3 flex-1 overflow-hidden rounded bg-slate-100"><div className="h-full bg-indigo-400" style={{ width: `${(n / max) * 100}%` }} /></div>
                  <span className="w-8 text-right text-sm tabular-nums">{n}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Recent failures">
          {data.recent_failures.length === 0 ? (
            <p className="text-sm text-slate-500">No failures. 🎉</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {data.recent_failures.map((f) => (
                <li key={f.id}>
                  <Link href={`/documents/${f.id}`} className="font-medium text-indigo-700 hover:underline">{f.filename}</Link>{" "}
                  <StatusBadge status={f.status} />
                  <p className="text-xs text-slate-500">{f.error}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Validation outcome (invoices & receipts)">
          <div className="flex flex-wrap gap-3">
            {Object.entries(data.validation_status_counts).map(([k, n]) => (
              <div key={k} className="flex items-center gap-2"><StatusBadge status={k} /><span className="tabular-nums">{n}</span></div>
            ))}
            {Object.keys(data.validation_status_counts).length === 0 && <p className="text-sm text-slate-500">No data yet.</p>}
          </div>
        </Card>
        <Card title="Shortcuts">
          <div className="flex flex-wrap gap-2">
            <Link className="btn-primary" href="/documents?status=needs_review">Review queue</Link>
            <Link className="btn-secondary" href="/upload">Upload</Link>
            <Link className="btn-secondary" href="/search">Search</Link>
          </div>
        </Card>
      </div>
    </div>
  );
}
