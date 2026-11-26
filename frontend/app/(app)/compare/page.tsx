"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Card, CardHeader, ErrorBox, Spinner, StatusBadge } from "@/components/ui";
import { api, type ComparisonDetail, type ComparisonRow, type DocumentRow, type Paginated } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { FIELD_LABELS, formatDate } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

function sourceText(src: Record<string, unknown>): string {
  if (!src || Object.keys(src).length === 0) return "";
  const file = typeof src.filename === "string" ? src.filename : "";
  if (typeof src.cell === "string") return `${file} · cell ${src.cell}`;
  if (src.page) return `${file} · page ${String(src.page)}${src.corrected ? " (corrected)" : ""}`;
  return file;
}

function CompareInner() {
  const params = useSearchParams();
  const { can } = useAuth();
  const docs = useAsync(() => api<Paginated<DocumentRow>>("/documents?size=100"), []);
  const past = useAsync(() => api<Paginated<ComparisonRow>>("/comparisons?size=10"), []);
  const [left, setLeft] = useState(params.get("left") ?? "");
  const [right, setRight] = useState(params.get("right") ?? "");
  const [result, setResult] = useState<ComparisonDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api<ComparisonDetail>("/comparisons", { method: "POST", json: { left_document_id: left, right_document_id: right } }));
      void past.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Comparison failed");
    } finally {
      setBusy(false);
    }
  }

  async function open(id: number) {
    try {
      setResult(await api<ComparisonDetail>(`/comparisons/${id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load");
    }
  }

  useEffect(() => {
    if (params.get("left") && params.get("right") && can("reviewer")) void run();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const options = (docs.data?.items ?? []).filter((d) => d.invoices === undefined || d.invoices > 0);
  const select = (value: string, set: (v: string) => void, label: string) => (
    <label className="flex-1 text-sm font-medium">
      {label}
      <select className="input mt-1" value={value} onChange={(e) => set(e.target.value)}>
        <option value="">Choose a document…</option>
        {options.map((d) => <option key={d.id} value={d.id}>{d.original_filename} ({d.invoices ?? 0})</option>)}
      </select>
    </label>
  );

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Cross-document verification</h1>
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          {select(left, setLeft, "Left document")}
          {select(right, setRight, "Right document")}
          <button className="btn-primary" disabled={!left || !right || left === right || busy || !can("reviewer")} onClick={run}>{busy ? "Comparing…" : "Compare"}</button>
        </div>
        <p className="pt-2 text-xs text-slate-500">Works for PDF vs PDF, PDF vs Excel/CSV, and invoice vs receipt. Records are matched by invoice number, then by supplier + total.</p>
      </Card>
      <ErrorBox message={error} />

      {result && (
        <div className="space-y-3">
          <Card title={`${result.left.filename} ↔ ${result.right.filename}`}>
            <div className="flex flex-wrap gap-4 text-sm">
              <span><b>{result.summary.pairs ?? 0}</b> matched pairs</span>
              <span className="text-emerald-700"><b>{result.summary.match ?? 0}</b> fully match</span>
              <span className="text-rose-700"><b>{result.summary.discrepancy ?? 0}</b> with discrepancies</span>
              <span className="text-amber-700"><b>{result.summary.uncertain ?? 0}</b> uncertain</span>
              <span><b>{result.summary.unmatched_left ?? 0}</b> only on left</span>
              <span><b>{result.summary.unmatched_right ?? 0}</b> only on right</span>
            </div>
          </Card>
          {result.pairs.map((p) => (
            <Card key={p.pair_index}>
            <CardHeader>
              <span>Pair {p.pair_index + 1}</span>
              <StatusBadge status={p.status} />
            </CardHeader>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-200">
                  <thead className="bg-slate-50"><tr><th className="th">Field</th><th className="th">Left</th><th className="th">Right</th><th className="th">Verdict</th><th className="th">Rule applied</th></tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {p.items.map((it, i) => (
                      <tr key={i} className={it.verdict === "mismatch" || it.verdict.startsWith("missing") ? "bg-rose-50/50" : ""}>
                        <td className="td font-medium">{FIELD_LABELS[it.field] ?? it.field}</td>
                        <td className="td">{it.left_value ?? "—"}<div className="text-xs text-slate-400">{sourceText(it.left_source)}</div></td>
                        <td className="td">{it.right_value ?? "—"}<div className="text-xs text-slate-400">{sourceText(it.right_source)}</div></td>
                        <td className="td"><StatusBadge status={it.verdict} /></td>
                        <td className="td text-xs text-slate-500">{it.rule}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Card title="Recent comparisons">
        {past.loading ? <Spinner /> : (past.data?.items.length ?? 0) === 0 ? <p className="text-sm text-slate-500">None yet.</p> : (
          <ul className="divide-y divide-slate-100 text-sm">
            {past.data?.items.map((c) => (
              <li key={c.id} className="flex items-center gap-3 py-1.5">
                <button className="font-medium text-indigo-700 hover:underline" onClick={() => open(c.id)}>#{c.id}</button>
                <span className="flex-1 truncate">{c.left} ↔ {c.right}</span>
                <span className="text-xs text-slate-500">{c.summary ? `${c.summary.discrepancy ?? 0} discrepancies` : ""} · {formatDate(c.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

export default function ComparePage() {
  return <Suspense fallback={<Spinner />}><CompareInner /></Suspense>;
}
