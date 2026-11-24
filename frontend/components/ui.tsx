"use client";

import type { ProcEvent } from "@/lib/api";
import { formatDate } from "@/lib/format";

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-800",
  approved: "bg-emerald-100 text-emerald-800",
  valid: "bg-emerald-100 text-emerald-800",
  match: "bg-emerald-100 text-emerald-800",
  done: "bg-emerald-100 text-emerald-800",
  needs_review: "bg-amber-100 text-amber-800",
  warnings: "bg-amber-100 text-amber-800",
  warning: "bg-amber-100 text-amber-800",
  uncertain: "bg-amber-100 text-amber-800",
  pending: "bg-slate-100 text-slate-700",
  not_comparable: "bg-slate-100 text-slate-600",
  failed: "bg-rose-100 text-rose-800",
  rejected: "bg-rose-100 text-rose-800",
  errors: "bg-rose-100 text-rose-800",
  error: "bg-rose-100 text-rose-800",
  mismatch: "bg-rose-100 text-rose-800",
  discrepancy: "bg-rose-100 text-rose-800",
  missing_in_left: "bg-rose-100 text-rose-800",
  missing_in_right: "bg-rose-100 text-rose-800",
  unmatched: "bg-rose-100 text-rose-800",
  duplicate: "bg-sky-100 text-sky-800",
  accepted: "bg-sky-100 text-sky-800",
};

export function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? "bg-indigo-100 text-indigo-800";
  return <span className={`inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{status.replaceAll("_", " ")}</span>;
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const color = pct >= 90 ? "bg-emerald-500" : pct >= 75 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="flex items-center gap-2" title={`confidence ${pct}%`}>
      <div className="h-1.5 w-14 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-slate-500">{pct}%</span>
    </div>
  );
}

export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-valuenow={Math.round(value * 100)}>
      <div className="h-full bg-indigo-500 transition-all" style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

export function ErrorBox({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800" role="alert">{message}</div>;
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return <p className="py-8 text-center text-sm text-slate-500">{label}</p>;
}

export function Pagination({ page, size, total, onChange }: { page: number; size: number; total: number; onChange: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className="flex items-center justify-between pt-3 text-sm text-slate-600">
      <span>{total} result{total === 1 ? "" : "s"}</span>
      <div className="flex items-center gap-2">
        <button className="btn-secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>Previous</button>
        <span>Page {page} of {pages}</span>
        <button className="btn-secondary" disabled={page >= pages} onClick={() => onChange(page + 1)}>Next</button>
      </div>
    </div>
  );
}

export function Timeline({ events }: { events: ProcEvent[] }) {
  if (events.length === 0) return <p className="text-sm text-slate-500">No events yet.</p>;
  return (
    <ol className="space-y-2">
      {events.map((e) => (
        <li key={e.id} className="flex gap-3 text-sm">
          <span className="w-44 shrink-0 text-xs text-slate-500">{formatDate(e.created_at)}</span>
          <StatusBadge status={e.status} />
          <span className="font-medium text-slate-700">{e.stage}</span>
          <span className="text-slate-600">{e.message}</span>
          {e.duration_ms !== null && <span className="ml-auto text-xs text-slate-400">{e.duration_ms} ms</span>}
        </li>
      ))}
    </ol>
  );
}

export function Card({ title, children, actions }: { title?: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between">
          {title && <h2 className="text-sm font-semibold text-slate-700">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}
