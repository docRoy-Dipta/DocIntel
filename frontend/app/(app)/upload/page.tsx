"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Card, CardHeader, ErrorBox, ProgressBar, StatusBadge } from "@/components/ui";
import {
  ACTIVE_STATUSES, ALLOWED_EXTENSIONS, MAX_UPLOAD_MB, api, uploadFiles,
  type DocStatus, type UploadItemResult,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatBytes } from "@/lib/format";

function validateLocally(file: File): string | null {
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!ALLOWED_EXTENSIONS.includes(ext)) return `Unsupported type ${ext || "(none)"}`;
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `Larger than ${MAX_UPLOAD_MB} MB`;
  if (file.size === 0) return "File is empty";
  return null;
}

export default function UploadPage() {
  const { can } = useAuth();
  const [queued, setQueued] = useState<File[]>([]);
  const [results, setResults] = useState<UploadItemResult[]>([]);
  const [statuses, setStatuses] = useState<Record<string, DocStatus>>({});
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const addFiles = useCallback((list: FileList | File[]) => {
    setQueued((prev) => [...prev, ...Array.from(list)]);
  }, []);

  async function send() {
    const good = queued.filter((f) => validateLocally(f) === null);
    if (good.length === 0) return;
    setError(null);
    setProgress(0);
    try {
      const res = await uploadFiles(good, setProgress);
      setResults((prev) => [...res.results, ...prev]);
      setQueued([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setProgress(null);
    }
  }

  // Poll processing progress of everything that was accepted.
  const idsKey = results.map((r) => r.document_id).filter(Boolean).join(",");
  useEffect(() => {
    const ids = Array.from(new Set(results.map((r) => r.document_id).filter((x): x is string => !!x)));
    if (ids.length === 0) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const entries = await Promise.all(ids.map((id) => api<DocStatus>(`/documents/${id}/status`).catch(() => null)));
      if (stop) return;
      setStatuses(Object.fromEntries(entries.filter((s): s is DocStatus => s !== null).map((s) => [s.id, s])));
      if (entries.some((s) => s && ACTIVE_STATUSES.includes(s.status))) timer = setTimeout(tick, 1500);
    };
    void tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [idsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!can("reviewer")) return <ErrorBox message="Your role (viewer) cannot upload documents." />;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Upload documents</h1>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
        className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-10 text-center ${dragging ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-white"}`}
      >
        <p className="font-medium">Drag & drop files here</p>
        <p className="text-sm text-slate-500">PDF, PNG, JPG, TIFF, XLSX, XLS, CSV · up to {MAX_UPLOAD_MB} MB each</p>
        <button className="btn-secondary mt-3" onClick={() => input.current?.click()}>Choose files…</button>
        <input ref={input} type="file" multiple hidden accept={ALLOWED_EXTENSIONS.join(",")} onChange={(e) => e.target.files && addFiles(e.target.files)} />
      </div>
      <ErrorBox message={error} />

      {queued.length > 0 && (
        <Card>
        <CardHeader>
          <span>Ready to upload ({queued.length})</span>
          <div className="flex gap-2"><button className="btn-secondary" onClick={() => setQueued([])}>Clear</button><button className="btn-primary" disabled={progress !== null} onClick={send}>Upload</button></div>
        </CardHeader>
          <ul className="divide-y divide-slate-100 text-sm">
            {queued.map((f, i) => {
              const problem = validateLocally(f);
              return (
                <li key={`${f.name}-${i}`} className="flex items-center gap-3 py-1.5">
                  <span className="flex-1 truncate">{f.name}</span>
                  <span className="text-slate-500">{formatBytes(f.size)}</span>
                  {problem ? <span className="text-rose-600">{problem}</span> : <StatusBadge status="pending" />}
                  <button className="text-xs text-slate-400 hover:text-rose-600" onClick={() => setQueued((q) => q.filter((_, j) => j !== i))}>remove</button>
                </li>
              );
            })}
          </ul>
          {progress !== null && <div className="pt-3"><ProgressBar value={progress} /><p className="pt-1 text-xs text-slate-500">Uploading… {Math.round(progress * 100)}%</p></div>}
        </Card>
      )}

      {results.length > 0 && (
        <Card>
        <CardHeader>
          <span>Processing</span>
        </CardHeader>
          <ul className="divide-y divide-slate-100 text-sm">
            {results.map((r, i) => {
              const st = r.document_id ? statuses[r.document_id] : undefined;
              return (
                <li key={`${r.filename}-${i}`} className="flex flex-wrap items-center gap-3 py-2">
                  <span className="min-w-0 flex-1 truncate font-medium">
                    {r.document_id ? <Link className="text-indigo-700 hover:underline" href={`/documents/${r.document_id}`}>{r.filename}</Link> : r.filename}
                  </span>
                  <StatusBadge status={r.status} />
                  {st && <StatusBadge status={st.status} />}
                  {st && <div className="w-40"><ProgressBar value={st.progress} /></div>}
                  {st && st.page_count > 0 && <span className="text-xs text-slate-500">{st.pages_done}/{st.page_count} pages</span>}
                  {r.reason && <span className="basis-full text-xs text-slate-500">{r.reason}</span>}
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </div>
  );
}
