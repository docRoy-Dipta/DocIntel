"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Card, ErrorBox, Pagination, Spinner, StatusBadge } from "@/components/ui";
import { api, type InvoiceRow, type Paginated, type SearchHit } from "@/lib/api";
import { formatMoney, splitHighlights } from "@/lib/format";

interface Filters {
  supplier: string; invoice_number: string; date_from: string; date_to: string; currency: string;
  min_total: string; max_total: string; status: string; needs_review: string;
}
const EMPTY: Filters = { supplier: "", invoice_number: "", date_from: "", date_to: "", currency: "", min_total: "", max_total: "", status: "", needs_review: "" };

function qs(filters: Filters, extra: Record<string, string>): string {
  const p = new URLSearchParams();
  Object.entries({ ...filters, ...extra }).forEach(([k, v]) => v !== "" && p.set(k, v));
  return p.toString();
}

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("hybrid");
  const [view, setView] = useState<"text" | "invoices">("text");
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [rows, setRows] = useState<Paginated<InvoiceRow> | null>(null);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("created_at");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(e?: FormEvent, nextPage = 1) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (view === "text") {
        if (!q.trim()) throw new Error("Enter some text to search for.");
        setHits(await api<SearchHit[]>(`/search?${qs(filters, { q, mode, limit: "30" })}`));
      } else {
        setRows(await api<Paginated<InvoiceRow>>(`/invoices?${qs(filters, { sort, page: String(nextPage), size: "25" })}`));
        setPage(nextPage);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setBusy(false);
    }
  }

  const set = (k: keyof Filters) => (e: { target: { value: string } }) => setFilters((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Search</h1>
      <form onSubmit={(e) => run(e)} className="card space-y-3">
        <div className="flex flex-wrap gap-2">
          <div className="flex rounded-lg border border-slate-300 p-0.5 text-sm">
            {(["text", "invoices"] as const).map((v) => (
              <button type="button" key={v} onClick={() => setView(v)} className={`rounded-md px-3 py-1 ${view === v ? "bg-indigo-600 text-white" : "text-slate-600"}`}>{v === "text" ? "Full text" : "Invoice list"}</button>
            ))}
          </div>
          {view === "text" ? (
            <>
              <input className="input min-w-64 flex-1" placeholder="Search the content of all documents…" value={q} onChange={(e) => setQ(e.target.value)} />
              <select className="input w-40" value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Search mode">
                <option value="hybrid">Hybrid</option><option value="keyword">Keyword</option><option value="semantic">Semantic</option>
              </select>
            </>
          ) : (
            <select className="input w-52" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
              <option value="created_at">Newest first</option><option value="invoice_date">Invoice date</option><option value="total_amount">Total</option><option value="supplier_name">Supplier</option>
            </select>
          )}
          <button className="btn-primary" disabled={busy}>{busy ? "Searching…" : "Search"}</button>
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
          <input className="input" placeholder="Supplier" value={filters.supplier} onChange={set("supplier")} />
          <input className="input" placeholder="Invoice number" value={filters.invoice_number} onChange={set("invoice_number")} />
          <input className="input" type="date" aria-label="From date" value={filters.date_from} onChange={set("date_from")} />
          <input className="input" type="date" aria-label="To date" value={filters.date_to} onChange={set("date_to")} />
          <input className="input" placeholder="Currency (USD)" maxLength={3} value={filters.currency} onChange={set("currency")} />
          <input className="input" type="number" placeholder="Min total" value={filters.min_total} onChange={set("min_total")} />
          <input className="input" type="number" placeholder="Max total" value={filters.max_total} onChange={set("max_total")} />
          <select className="input" value={filters.status} onChange={set("status")} aria-label="Document status">
            <option value="">Any status</option><option value="completed">completed</option><option value="needs_review">needs review</option>
          </select>
          <select className="input" value={filters.needs_review} onChange={set("needs_review")} aria-label="Needs review">
            <option value="">Review: any</option><option value="true">Needs review</option><option value="false">No review needed</option>
          </select>
          <button type="button" className="btn-secondary" onClick={() => setFilters(EMPTY)}>Clear filters</button>
        </div>
      </form>
      <ErrorBox message={error} />

      {view === "text" && hits && (
        <div className="space-y-2">
          <p className="text-sm text-slate-500">{hits.length} result(s)</p>
          {hits.map((h) => (
            <Card key={`${h.document_id}-${h.page_number}`}>
              <div className="flex flex-wrap items-center gap-2">
                <Link href={`/documents/${h.document_id}`} className="font-medium text-indigo-700 hover:underline">{h.filename}</Link>
                <span className="text-xs text-slate-500">page {h.page_number}</span>
                {h.sources.map((s) => <StatusBadge key={s} status={s} />)}
                {h.logical && <span className="text-xs text-slate-500">{h.logical.invoice_number ?? ""} · {h.logical.supplier_name ?? ""} · {formatMoney(h.logical.total_amount, h.logical.currency)}</span>}
                <span className="ml-auto text-xs tabular-nums text-slate-400">score {h.score.toFixed(3)}</span>
              </div>
              <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">
                {splitHighlights(h.snippet).map((part, i) => part.hit ? <mark key={i} className="rounded bg-yellow-200 px-0.5">{part.text}</mark> : <span key={i}>{part.text}</span>)}
              </p>
            </Card>
          ))}
        </div>
      )}

      {view === "invoices" && (busy && !rows ? <Spinner /> : rows && (
        <>
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50"><tr><th className="th">Invoice</th><th className="th">Supplier</th><th className="th">Customer</th><th className="th">Date</th><th className="th">Total</th><th className="th">Validation</th><th className="th">File</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {rows.items.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50">
                    <td className="td font-medium">{r.invoice_number ?? "—"}<div className="text-xs text-slate-400">{r.doc_type}</div></td>
                    <td className="td">{r.supplier_name ?? "—"}</td><td className="td">{r.customer_name ?? "—"}</td><td className="td">{r.invoice_date ?? "—"}</td>
                    <td className="td tabular-nums">{formatMoney(r.total_amount, r.currency)}</td>
                    <td className="td"><StatusBadge status={r.validation_status} />{r.needs_review && <span className="ml-1"><StatusBadge status="needs_review" /></span>}</td>
                    <td className="td"><Link className="text-indigo-700 hover:underline" href={`/documents/${r.document_id}`}>{r.filename}</Link> <span className="text-xs text-slate-400">p.{r.start_page}</span></td>
                  </tr>
                ))}
                {rows.items.length === 0 && <tr><td className="td py-8 text-center text-slate-500" colSpan={7}>No invoices match these filters.</td></tr>}
              </tbody>
            </table>
          </div>
          <Pagination page={page} size={rows.size} total={rows.total} onChange={(p) => void run(undefined, p)} />
        </>
      ))}
    </div>
  );
}
