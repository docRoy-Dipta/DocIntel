// Thin typed client for the backend API.
// The access token lives in localStorage: simple, but readable by any script running on this origin,
// so the app must never render untrusted HTML (React escapes all text, and we never use innerHTML).

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "docint.token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

type Options = Omit<RequestInit, "body"> & { json?: unknown; body?: BodyInit | null };

async function request(path: string, options: Options = {}): Promise<Response> {
  const headers = new Headers(options.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = options.body ?? null;
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.json);
  }
  const res = await fetch(`${API_BASE}/api/v1${path}`, { ...options, headers, body });
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/auth/login")) {
      setToken(null);
      if (typeof window !== "undefined") window.location.href = "/login";
    }
    let code = "error";
    let message = res.statusText || "Request failed";
    try {
      const data = (await res.json()) as { error?: { code?: string; message?: string } };
      code = data.error?.code ?? code;
      message = data.error?.message ?? message;
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(res.status, code, message);
  }
  return res;
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const res = await request(path, options);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function apiBlob(path: string): Promise<Blob> {
  return (await request(path)).blob();
}

/** Upload with progress (fetch cannot report upload progress, XHR can). */
export function uploadFiles(files: File[], onProgress: (fraction: number) => void): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/v1/documents`);
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText) as Partial<UploadResponse> & { error?: { code: string; message: string } };
        if ((xhr.status === 202 || xhr.status === 422) && data.results) return resolve({ results: data.results });
        reject(new ApiError(xhr.status, data.error?.code ?? "error", data.error?.message ?? "Upload failed"));
      } catch {
        reject(new ApiError(xhr.status, "error", "Upload failed"));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "Network error during upload"));
    xhr.send(form);
  });
}

// ----------------------------------------------------------------------------- types

export type Role = "admin" | "reviewer" | "viewer";
export interface User { id: number; email: string; role: Role; is_active: boolean }
export interface Paginated<T> { items: T[]; total: number; page: number; size: number }

export interface DocumentRow {
  id: string; original_filename: string; kind: string; mime_type: string; size_bytes: number; status: string;
  page_count: number; pages_done: number; error_message: string | null; created_at: string; updated_at: string;
  invoices?: number; needs_review?: number;
}
export interface UploadItemResult { filename: string; status: "accepted" | "duplicate" | "rejected"; document_id: string | null; reason: string | null }
export interface UploadResponse { results: UploadItemResult[] }
export interface DocStatus {
  id: string; status: string; page_count: number; pages_done: number; progress: number;
  error_message: string | null; logical_documents: number; extractions_done: number;
}
export interface ProcEvent {
  id: number; stage: string; status: string; message: string | null; detail: unknown;
  duration_ms: number | null; logical_document_id: number | null; created_at: string;
}
export type Bbox = number[] | { sheet?: string; cell?: string } | null;
export interface Field {
  name: string; value: string | null; original_value: string | null; corrected: boolean; confidence: number;
  source: string; grounded: boolean; page: number | null; bbox: Bbox; raw_text: string | null;
}
export interface LineItem {
  id: number; position: number; description: string | null; quantity: string | null; unit_price: string | null;
  amount: string | null; page: number | null; raw_text: string | null; bbox: Bbox; confidence: number;
}
export interface ValidationIssue {
  rule_code: string; severity: "error" | "warning" | "info"; message: string; field: string | null;
  expected: string | null; actual: string | null;
}
export interface Correction {
  id: number; target_type: string; field_name: string; line_item_position: number | null;
  old_value: string | null; new_value: string | null; reason: string | null; user_id: number | null; created_at: string;
}
export interface Logical {
  id: number; document_id: string; filename: string | null; position: number; doc_type: string;
  start_page: number; end_page: number; source: string; extraction_status: string; error: string | null;
  review_status: string; needs_review: boolean; validation_status: string; overall_confidence: number | null;
  extraction_version: number | null; provider: string | null; fields: Field[]; line_items: LineItem[];
  validation: ValidationIssue[]; corrections: Correction[];
}
export interface PageInfo {
  page_number: number; label: string | null; status: string; method: string | null; char_count: number;
  ocr_confidence: number | null; width: number | null; height: number | null; error: string | null;
}
export interface PageDetail extends PageInfo { text: string; layout: unknown }
export interface InvoiceRow {
  id: number; document_id: string; filename: string; document_status: string; doc_type: string; start_page: number;
  end_page: number; invoice_number: string | null; supplier_name: string | null; customer_name: string | null;
  invoice_date: string | null; total_amount: string | null; currency: string | null; needs_review: boolean;
  review_status: string; validation_status: string;
}
export interface SearchHit {
  document_id: string; filename: string; page_number: number; score: number; snippet: string; sources: string[];
  logical: { id: number; doc_type: string; invoice_number: string | null; supplier_name: string | null;
    total_amount: string | null; currency: string | null; needs_review: boolean } | null;
}
export interface CompareItem {
  field: string; left_value: string | null; right_value: string | null; left_source: Record<string, unknown>;
  right_source: Record<string, unknown>; verdict: string; rule: string | null;
}
export interface ComparePair {
  pair_index: number; left_logical_id: number | null; right_logical_id: number | null; status: string; items: CompareItem[];
}
export interface ComparisonDetail {
  id: number; created_at: string; summary: Record<string, number>;
  left: { id: string | null; filename: string | null }; right: { id: string | null; filename: string | null };
  pairs: ComparePair[];
}
export interface ComparisonRow {
  id: number; created_at: string; summary: Record<string, number> | null; left: string | null; right: string | null;
}
export interface Dashboard {
  documents_total: number; by_status: Record<string, number>; success_rate: number | null; failure_rate: number | null;
  review_queue: number; logical_documents_by_type: Record<string, number>; validation_status_counts: Record<string, number>;
  pages_processed: number; pages_ocr: number; uploads_last_7_days: number; avg_processing_seconds: number | null;
  recent_failures: { id: string; filename: string; status: string; error: string | null }[];
}
export interface AuditEntry {
  id: number; user_id: number | null; action: string; entity_type: string | null; entity_id: string | null;
  detail: unknown; ip: string | null; created_at: string;
}

export const ACTIVE_STATUSES = ["uploaded", "queued", "validating", "processing", "analyzing"];
export const ALLOWED_EXTENSIONS = [".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".xlsx", ".xls", ".csv"];
export const MAX_UPLOAD_MB = 200;
