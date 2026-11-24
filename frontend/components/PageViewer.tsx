"use client";

import { api, type Bbox, type PageDetail } from "@/lib/api";
import { useAsync, useBlobUrl } from "@/lib/hooks";
import { ErrorBox, Spinner } from "./ui";

interface SheetLayout { kind: "sheet"; total_rows: number; rows: string[][]; warnings: string[] }

function isSheet(layout: unknown): layout is SheetLayout {
  return typeof layout === "object" && layout !== null && (layout as { kind?: string }).kind === "sheet";
}

function parseCell(ref: string | undefined): { row: number; col: number } | null {
  const m = /!?([A-Z]+)(\d+)$/.exec(ref ?? "");
  if (!m) return null;
  let col = 0;
  for (const ch of m[1] ?? "") col = col * 26 + (ch.charCodeAt(0) - 64);
  return { row: Number(m[2]), col };
}

/** Shows one page of a document: an image with a highlighted box (PDF/image) or a table (spreadsheet). */
export function PageViewer({ docId, kind, page, highlight }: { docId: string; kind: string; page: number; highlight: Bbox }) {
  const isSpreadsheet = kind === "xlsx" || kind === "xls" || kind === "csv";
  const info = useAsync(() => api<PageDetail>(`/documents/${docId}/pages/${page}`), [docId, page]);
  const image = useBlobUrl(isSpreadsheet ? null : `/documents/${docId}/pages/${page}/image?dpi=110`);

  if (info.loading) return <Spinner label="Loading page…" />;
  if (info.error || !info.data) return <ErrorBox message={info.error ?? "Page not found"} />;
  const p = info.data;

  if (isSpreadsheet && isSheet(p.layout)) {
    const cell = highlight && !Array.isArray(highlight) ? parseCell(highlight.cell) : null;
    return (
      <div className="overflow-auto rounded-lg border border-slate-200 bg-white">
        <p className="border-b px-3 py-1 text-xs text-slate-500">
          Sheet “{p.label}” — first {p.layout.rows.length} of {p.layout.total_rows} rows
        </p>
        <table className="min-w-full text-xs">
          <tbody>
            {p.layout.rows.map((row, r) => (
              <tr key={r} className="border-t border-slate-100">
                <td className="bg-slate-50 px-2 py-1 text-right text-slate-400">{r + 1}</td>
                {row.map((value, c) => {
                  const hit = cell !== null && cell.row === r + 1 && cell.col === c + 1;
                  return (
                    <td key={c} className={`whitespace-nowrap px-2 py-1 ${hit ? "bg-yellow-200 font-semibold ring-2 ring-yellow-500" : ""}`}>{value}</td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const box = Array.isArray(highlight) && highlight.length === 4 && p.width && p.height ? highlight : null;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
        <span>Page {page} · {p.method ?? "?"}{p.ocr_confidence !== null ? ` · OCR ${(p.ocr_confidence * 100).toFixed(0)}%` : ""}</span>
        {p.error && <span className="text-rose-600">{p.error}</span>}
      </div>
      {image.error && <ErrorBox message={image.error} />}
      {!image.url && !image.error && <Spinner label="Rendering page…" />}
      {image.url && (
        <div className="relative inline-block w-full overflow-hidden rounded-lg border border-slate-200 bg-white">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={image.url} alt={`Page ${page}`} className="block w-full" />
          {box && p.width && p.height && (
            <div
              className="pointer-events-none absolute rounded-sm border-2 border-indigo-600 bg-indigo-500/20"
              style={{
                left: `${((box[0] ?? 0) / p.width) * 100}%`,
                top: `${((box[1] ?? 0) / p.height) * 100}%`,
                width: `${(((box[2] ?? 0) - (box[0] ?? 0)) / p.width) * 100}%`,
                height: `${(((box[3] ?? 0) - (box[1] ?? 0)) / p.height) * 100}%`,
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}
