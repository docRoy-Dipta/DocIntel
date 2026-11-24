"use client";

import Link from "next/link";
import { Card, ErrorBox, Spinner, StatusBadge } from "@/components/ui";
import { api, type Dashboard } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { percent } from "@/lib/format";

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="card relative overflow-hidden border-l-4 border-l-orange-400">
      <p className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">{label}</p>
      <p className="mt-2 text-3xl font-semibold tabular-nums text-indigo-950">{value}</p>
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
    <div className="space-y-6">
      <section className="relative isolate overflow-hidden rounded-[1.75rem] bg-indigo-950 px-6 py-8 text-white shadow-md sm:px-8 md:py-10">
        <div aria-hidden="true" className="pointer-events-none absolute -right-20 -top-36 h-80 w-80 rounded-full border-[40px] border-orange-400/10 bg-white/[0.03]" />
        <div aria-hidden="true" className="pointer-events-none absolute bottom-0 right-1/3 h-px w-1/2 bg-gradient-to-r from-transparent via-orange-300/40 to-transparent" />
        <div className="relative flex flex-col gap-8 md:flex-row md:items-end md:justify-between">
          <div className="max-w-2xl">
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-orange-300">Your document workspace</p>
            <h1 className="mt-3 font-display text-4xl leading-tight sm:text-5xl">A clearer view of every document.</h1>
            <p className="mt-4 max-w-xl text-sm leading-6 text-indigo-100 sm:text-base">
              Follow each file from upload to verified details, with review work and evidence all in one place.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link className="btn-primary" href="/upload">Upload documents</Link>
              <Link className="btn border border-white/25 bg-white/5 text-white hover:bg-white/10" href="/documents">Browse documents</Link>
            </div>
          </div>
          <div className="relative flex min-w-48 items-center gap-4 rounded-2xl border border-white/15 bg-white/[0.07] p-5 backdrop-blur-sm">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-orange-400/15 text-orange-200">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="h-6 w-6" stroke="currentColor" strokeWidth="1.7">
                <path d="M7 3.75h7l4 4v12.5H7a2 2 0 0 1-2-2v-12.5a2 2 0 0 1 2-2Z" />
                <path d="M14 3.75v4h4M8.5 12h7M8.5 15.5h7" />
              </svg>
            </span>
            <div>
              <p className="text-xs font-medium text-indigo-200">Documents in workspace</p>
              <p className="mt-1 text-3xl font-semibold tabular-nums">{data.documents_total}</p>
            </div>
          </div>
        </div>
      </section>

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
