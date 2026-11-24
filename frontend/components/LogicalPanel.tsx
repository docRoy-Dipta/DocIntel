"use client";

import { useState } from "react";
import { api, type Bbox, type Field, type LineItem, type Logical } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { FIELD_LABELS, formatDate, formatMoney } from "@/lib/format";
import { ConfidenceBar, ErrorBox, StatusBadge } from "./ui";

interface Props {
  logical: Logical;
  onChange: (updated: Logical) => void;
  onSelect: (page: number | null, bbox: Bbox) => void;
  selectedField: string | null;
}

const SOURCE_STYLE: Record<string, string> = {
  extracted: "text-slate-500",
  inferred: "text-amber-700 font-medium",
  corrected: "text-indigo-700 font-medium",
};

export function LogicalPanel({ logical, onChange, onSelect, selectedField }: Props) {
  const { can } = useAuth();
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canEdit = can("viewer");
  const isSheet = logical.source === "spreadsheet";

  async function saveField(field: Field) {
    setBusy(true);
    setError(null);
    try {
      const updated = await api<Logical>(`/logical-documents/${logical.id}/fields/${field.name}`, {
        method: "PATCH",
        json: { value: draft.trim() === "" ? null : draft, reason: reason || null },
      });
      onChange(updated);
      setEditing(null);
      setReason("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  async function saveLine(item: LineItem, column: "description" | "quantity" | "unit_price" | "amount", value: string) {
    setError(null);
    try {
      onChange(await api<Logical>(`/line-items/${item.id}`, { method: "PATCH", json: { [column]: value } }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    }
  }

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      onChange(await api<Logical>(`/logical-documents/${logical.id}/approve`, { method: "POST" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not approve");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={logical.validation_status} />
        {logical.needs_review && <StatusBadge status="needs_review" />}
        <StatusBadge status={logical.review_status === "approved" ? "approved" : "pending"} />
        <span className="text-xs text-slate-500">
          {logical.provider ?? "—"} · v{logical.extraction_version ?? "—"} · overall confidence{" "}
          {logical.overall_confidence !== null ? `${Math.round(logical.overall_confidence * 100)}%` : "—"}
        </span>
        {canEdit && logical.review_status !== "approved" && (
          <button className="btn-primary ml-auto" disabled={busy} onClick={approve}>Approve</button>
        )}
      </div>
      <ErrorBox message={error ?? logical.error} />

      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr><th className="th">Field</th><th className="th">Value</th><th className="th">Confidence</th><th className="th">Origin</th><th className="th" /></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {logical.fields.filter((f) => f.name !== "tax_rate" || f.value !== null).map((f) => (
              <tr
                key={f.name}
                className={`cursor-pointer ${selectedField === f.name ? "bg-indigo-50" : "hover:bg-slate-50"}`}
                onClick={() => onSelect(f.page, f.bbox)}
              >
                <td className="td font-medium">{FIELD_LABELS[f.name] ?? f.name}</td>
                <td className="td">
                  {editing === f.name ? (
                    <div className="space-y-1" onClick={(e) => e.stopPropagation()}>
                      <input className="input" value={draft} autoFocus onChange={(e) => setDraft(e.target.value)} aria-label={`New value for ${f.name}`} />
                      <input className="input" placeholder="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)} />
                      <div className="flex gap-2">
                        <button className="btn-primary" disabled={busy} onClick={() => saveField(f)}>Save</button>
                        <button className="btn-secondary" onClick={() => setEditing(null)}>Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {f.value ?? <span className="text-slate-400">— not found —</span>}
                      {f.corrected && f.original_value !== f.value && (
                        <div className="text-xs text-slate-400">was: {f.original_value ?? "—"}</div>
                      )}
                      {!f.grounded && <div className="text-xs text-rose-600">Value could not be found in the source and was dropped</div>}
                    </>
                  )}
                </td>
                <td className="td"><ConfidenceBar value={f.confidence} /></td>
                <td className={`td text-xs ${SOURCE_STYLE[f.source] ?? ""}`}>{f.source}{f.page ? ` · p.${f.page}` : ""}</td>
                <td className="td text-right">
                  {canEdit && editing !== f.name && (
                    <button
                      className="text-xs font-medium text-indigo-600 hover:underline"
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditing(f.name);
                        setDraft(f.value ?? "");
                      }}
                    >
                      Edit
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <h3 className="mb-1 text-sm font-semibold text-slate-700">Line items ({logical.line_items.length})</h3>
        {logical.line_items.length === 0 ? (
          <p className="text-sm text-slate-500">No line items were found.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr><th className="th">#</th><th className="th">Description</th><th className="th">Qty</th><th className="th">Unit price</th><th className="th">Amount</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {logical.line_items.map((li) => (
                  <tr key={li.id} className="cursor-pointer hover:bg-slate-50" onClick={() => onSelect(li.page, li.bbox)}>
                    <td className="td text-slate-400">{li.position}</td>
                    <td className="td">{li.description ?? "—"}</td>
                    {(["quantity", "unit_price", "amount"] as const).map((col) => (
                      <td key={col} className="td tabular-nums">
                        {canEdit && !isSheet ? (
                          <input
                            className="w-24 rounded border border-transparent bg-transparent px-1 py-0.5 text-right hover:border-slate-300 focus:border-indigo-500 focus:outline-none"
                            defaultValue={li[col] ?? ""}
                            aria-label={`${col} of line ${li.position}`}
                            onClick={(e) => e.stopPropagation()}
                            onBlur={(e) => {
                              const v = e.target.value.trim();
                              if (v !== (li[col] ?? "")) void saveLine(li, col, v);
                            }}
                          />
                        ) : (
                          formatMoney(li[col])
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div>
        <h3 className="mb-1 text-sm font-semibold text-slate-700">Validation ({logical.validation.length})</h3>
        {logical.validation.length === 0 ? (
          <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">All deterministic checks passed.</p>
        ) : (
          <ul className="space-y-1">
            {logical.validation.map((v, i) => (
              <li key={i} className="flex flex-wrap items-start gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                <StatusBadge status={v.severity} />
                <span className="font-mono text-xs text-slate-500">{v.rule_code}</span>
                <span className="flex-1">{v.message}</span>
                {(v.expected || v.actual) && (
                  <span className="text-xs text-slate-500">expected {v.expected ?? "—"} · found {v.actual ?? "—"}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {logical.corrections.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-semibold text-slate-700">Correction history</h3>
          <ul className="space-y-1 text-sm">
            {logical.corrections.map((c) => (
              <li key={c.id} className="rounded-lg bg-slate-50 px-3 py-1.5">
                <span className="font-medium">{FIELD_LABELS[c.field_name] ?? c.field_name}</span>
                {c.line_item_position !== null && ` (line ${c.line_item_position})`}: “{c.old_value ?? "—"}” → “{c.new_value ?? "—"}”
                <span className="text-xs text-slate-400"> · {formatDate(c.created_at)}{c.reason ? ` · ${c.reason}` : ""}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
