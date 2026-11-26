"use client";

import Link from "next/link";
import { Card, CardHeader, CardContent, ErrorBox, Spinner, StatusBadge } from "@/components/ui";
import { api, type Dashboard } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { percent } from "@/lib/format";

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Card className="relative overflow-hidden border-l-4 border-l-[#2d5a82]">
      <CardContent className="space-y-2">
        <p className="text-xs font-bold uppercase tracking-[0.14em] text-[#6b7280]">{label}</p>
        <p className="mt-2 text-3xl font-semibold tabular-nums text-[#141923]">{value}</p>
        {hint && <p className="text-xs text-[#6b7280]">{hint}</p>}
      </CardContent>
    </Card>
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
      <section className="relative isolate overflow-hidden rounded-[1.75rem] bg-[#2d5a82] px-6 py-8 text-white shadow-md sm:px-8 md:py-10">
        <div aria-hidden="true" className="pointer-events-none absolute -right-20 -top-36 h-80 w-80 rounded-full border-[40px] border-[#f47260]/10 bg-white/[0.03]" />
        <div aria-hidden="true" className="pointer-events-none absolute bottom-0 right-1/3 h-px w-1/2 bg-gradient-to-r from-transparent via-[#f47260]/40 to-transparent" />
        <div className="relative flex flex-col gap-8 md:flex-row md:items-end md:justify-between">
          <div className="max-w-2xl">
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-[#f1f3f6]">Your document workspace</p>
            <h1 className="mt-3 font-display text-4xl leading-tight sm:text-5xl">A clearer view of every document.</h1>
            <p className="mt-4 max-w-xl text-sm leading-6 text-[#dbe3f0] sm:text-base">
              Follow each file from upload to verified details, with review work and evidence all in one place.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link href="/upload" className="inline-flex items-center justify-center gap-2 rounded-[0.6rem] bg-[#2d5a82] text-white hover:bg-[#244a6b] active:bg-[#1e3d58] shadow-sm hover:shadow-md font-medium transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-[#2d5a82] focus-visible:ring-offset-2 px-4 py-2.5 text-sm w-full lg:w-auto">
                Upload documents
              </Link>
              <Link href="/documents" className="inline-flex items-center justify-center gap-2 rounded-[0.6rem] border border-[#d8dce4] bg-white text-[#141923] hover:bg-[#f5f7fa] font-medium transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-[#2d5a82] focus-visible:ring-offset-2 px-4 py-2.5 text-sm w-full lg:w-auto">
                Browse documents
              </Link>
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
              <p className="text-xs font-medium text-[#f1f3f6]">Documents in workspace</p>
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
        <Card>
          <CardHeader className="flex items-center justify-between">
            <span className="font-semibold text-[#141923]">Documents by status</span>
            <Link href="/upload" className="text-sm font-medium text-[#2d5a82] hover:underline">Upload documents</Link>
          </CardHeader>
          <CardContent className="space-y-2">
            {statuses.length === 0 ? (
              <p className="text-sm text-[#6b7280]">Nothing uploaded yet.</p>
            ) : (
              <ul className="space-y-2">
                {statuses.map(([status, n]) => (
                  <li key={status} className="flex items-center gap-3">
                    <Link href={`/documents?status=${status}`} className="w-32"><StatusBadge status={status} /></Link>
                    <div className="h-3 flex-1 overflow-hidden rounded bg-[#f1f3f6]"><div className="h-full bg-[#2d5a82]" style={{ width: `${(n / max) * 100}%` }} /></div>
                    <span className="w-8 text-right text-sm tabular-nums">{n}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <span className="font-semibold text-[#141923]">Recent failures</span>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.recent_failures.length === 0 ? (
              <p className="text-sm text-[#2e7d4f]">No failures. 🎉</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {data.recent_failures.map((f) => (
                  <li key={f.id}>
                    <Link href={`/documents/${f.id}`} className="font-medium text-[#2d5a82] hover:underline">{f.filename}</Link> <StatusBadge status={f.status} />
                    <p className="text-xs text-[#6b7280]">{f.error}</p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <span className="font-semibold text-[#141923]">Validation outcome (invoices & receipts)</span>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex flex-wrap gap-3">
              {Object.entries(data.validation_status_counts).map(([k, n]) => (
                <div key={k} className="flex items-center gap-2"><StatusBadge status={k} /><span className="tabular-nums">{n}</span></div>
              ))}
              {Object.keys(data.validation_status_counts).length === 0 && <p className="text-sm text-[#6b7280]">No data yet.</p>}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <span className="font-semibold text-[#141923]">Shortcuts</span>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex flex-wrap gap-2">
              <Link className="btn-primary" href="/documents?status=needs_review">Review queue</Link>
              <Link className="btn-secondary" href="/upload">Upload</Link>
              <Link className="btn-secondary" href="/search">Search</Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
