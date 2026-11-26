"use client";

import * as React from "react";
import { useState, useCallback, useEffect, useRef, type ReactNode } from "react";
import { ChevronRight, LogOut, Mail, Phone, Shield, User, Clock, FileText, PieChart, Activity, ShieldCheck, Download, Plus, Edit, Delete, Trash2, Search, Filter, Clock as ClockIcon } from "lucide-react";

import type { ProcEvent } from "@/lib/api";
import { formatDate } from "@/lib/format";

// -----------------------------------------------------------------------------
// Toast system
// -----------------------------------------------------------------------------

type ToastType = "success" | "error" | "warning" | "info";

interface Toast {
  id: string;
  title: string;
  description?: string;
  type: ToastType;
}

const TOAST_STYLES: Record<ToastType, string> = {
  success: "bg-[#eef7f1] border-[#b9e2ca] text-[#1e6b3a]",
  error: "bg-[#fbeaea] border-[#f4c7c7] text-[#b3261e]",
  warning: "bg-[#fdf3e3] border-[#f6e3b4] text-[#9a6100]",
  info: "bg-[#eef3f9] border-[#dbe3f0] text-[#2d5a82]",
};

let toastContainer: HTMLElement | null = null;
let toasts: Toast[] = [];

function getContainer() {
  if (!toastContainer) {
    toastContainer = document.createElement("div");
    toastContainer.className = "fixed bottom-5 right-5 z-50 flex flex-col gap-2 pointer-events-none";
    document.body.appendChild(toastContainer);
  }
  return toastContainer;
}

export function toast({ title, description, type = "info" }: { title: string; description?: string; type?: ToastType }) {
  const id = Math.random().toString(36).slice(2);
  const newToast: Toast = { id, title, description, type };
  toasts = [newToast, ...toasts].slice(0, 5);
  renderToasts();
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id);
    renderToasts();
  }, 5000);
}

function renderToasts() {
  const container = getContainer();
  container.innerHTML = "";
  container.style.pointerEvents = "auto";
  toasts.forEach((t) => {
    const el = document.createElement("div");
    el.className = `rounded-[1rem] border border-[#d8dce4] bg-white shadow-lg p-4 flex items-start gap-3 min-w-[300px] pointer-events-auto ${TOAST_STYLES[t.type]}`;
    const iconMap: Record<ToastType, string> = {
      success: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>',
      error: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>',
      warning: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>',
      info: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>',
    };
    el.innerHTML = `
      <div class="shrink-0">${iconMap[t.type]}</div>
      <div>
        <h4 class="text-sm font-semibold">${t.title}</h4>
        ${t.description ? `<p class="text-xs text-opacity-80 mt-0.5">${t.description}</p>` : ""}
      </div>
      <button class="ml-auto text-[#8a94a6] hover:text-[#141923] transition-colors" onclick="this.parentElement.remove()">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
      </button>
    `;
    container.appendChild(el);
  });
}

// -----------------------------------------------------------------------------
// StatusBadge
// -----------------------------------------------------------------------------

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-[#eef7f1] text-[#2e7d4f]",
  approved: "bg-[#eef7f1] text-[#2e7d4f]",
  valid: "bg-[#eef7f1] text-[#2e7d4f]",
  match: "bg-[#eef7f1] text-[#2e7d4f]",
  done: "bg-[#eef7f1] text-[#2e7d4f]",
  needs_review: "bg-[#fdf3e3] text-[#b26a00]",
  warnings: "bg-[#fdf3e3] text-[#b26a00]",
  warning: "bg-[#fdf3e3] text-[#b26a00]",
  uncertain: "bg-[#fdf3e3] text-[#b26a00]",
  pending: "bg-[#f1f3f6] text-[#5c6674]",
  not_comparable: "bg-[#f1f3f6] text-[#5c6674]",
  failed: "bg-[#fbeaea] text-[#b3261e]",
  rejected: "bg-[#fbeaea] text-[#b3261e]",
  errors: "bg-[#fbeaea] text-[#b3261e]",
  error: "bg-[#fbeaea] text-[#b3261e]",
  mismatch: "bg-[#fbeaea] text-[#b3261e]",
  discrepancy: "bg-[#fbeaea] text-[#b3261e]",
  missing_in_left: "bg-[#fbeaea] text-[#b3261e]",
  missing_in_right: "bg-[#fbeaea] text-[#b3261e]",
  unmatched: "bg-[#fbeaea] text-[#b3261e]",
  duplicate: "bg-[#eef3f9] text-[#2d5a82]",
  accepted: "bg-[#eef3f9] text-[#2d5a82]",
  uploaded: "bg-[#f1f3f6] text-[#5c6674]",
  queued: "bg-[#f1f3f6] text-[#5c6674]",
  processing: "bg-[#eef3f9] text-[#2d5a82]",
  analyzing: "bg-[#eef3f9] text-[#2d5a82]",
};

export function StatusBadge({ status, className = "" }: { status: string; className?: string }) {
  const cls = STATUS_STYLES[status] ?? "bg-[#f1f3f6] text-[#5c6674]";
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${cls} ${className}`}>
      {status.replaceAll("_", " ")}
    </span>
  );
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const color = pct >= 90 ? "bg-[#2e7d4f]" : pct >= 75 ? "bg-[#b26a00]" : "bg-[#b3261e]";
  return (
    <div className="flex items-center gap-2" title={`confidence ${pct}%`}>
      <div className="h-[6px] w-[64px] overflow-hidden rounded-full bg-[#e2e5ec]">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] tabular-nums text-[#6b7280]">{pct}%</span>
    </div>
  );
}

export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-[6px] w-full overflow-hidden rounded-full bg-[#e2e5ec]" role="progressbar" aria-valuenow={Math.round(value * 100)}>
      <div className="h-full bg-[#2d5a82] transition-all" style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

export function ErrorBox({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="rounded-lg border border-[#f4c7c7] bg-[#fbeaea] px-3 py-2 text-sm text-[#b3261e]" role="alert">{message}</div>;
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return <div className="flex items-center justify-center py-8"><div className="w-8 h-8 border-4 border-[#e2e5ec] border-t-[#2d5a82] rounded-full animate-spin" /><span className="ml-3 text-sm text-[#6b7280]">{label}</span></div>;
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

export function Card({ children, className = "", elevated = false, ...props }: { children?: ReactNode; className?: string; elevated?: boolean } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`rounded-[1rem] border border-[#e2e5ec] bg-white ${elevated ? "shadow-[0_4px_20px_-6px_rgba(20,25,33,0.06)]" : "shadow-sm"} ${className}`} {...props}>
      {children}
    </div>
  );
}

export function CardHeader({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <div className={`px-4 py-3 border-b border-[#f1f3f6] flex items-center justify-between gap-3 ${className}`}>{children}</div>;
}

export function CardContent({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <div className={`px-4 py-3 ${className}`}>{children}</div>;
}

export function CardFooter({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <div className={`px-4 py-3 border-t border-[#f1f3f6] bg-[#f8fafc]/50 rounded-b-[1rem] ${className}`}>{children}</div>;
}

// -----------------------------------------------------------------------------
// Button
// -----------------------------------------------------------------------------

export function Button({
  children,
  className = "",
  variant = "primary",
  size = "default",
  disabled = false,
  loading = false,
  onClick,
  ...props
}: {
  children?: ReactNode;
  className?: string;
  variant?: "primary" | "secondary" | "ghost" | "danger" | "outline";
  size?: "default" | "sm" | "lg";
  disabled?: boolean;
  loading?: boolean;
  onClick?: (() => void) | React.MouseEventHandler<HTMLButtonElement>;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const variants: Record<string, string> = {
    primary: "bg-[#2d5a82] text-white hover:bg-[#244a6b] active:bg-[#1e3d58] shadow-sm hover:shadow-md",
    secondary: "border border-[#d8dce4] bg-white text-[#141923] hover:bg-[#f5f7fa] active:bg-[#eef1f6]",
    ghost: "text-[#5c6674] hover:bg-[#f5f7fa] hover:text-[#141923]",
    danger: "bg-[#aa373c] text-white hover:bg-[#902e33] active:bg-[#7a262b] shadow-sm hover:shadow-md",
    outline: "border border-[#d8dce4] text-[#141923] hover:bg-[#f5f7fa]",
  };
  const sizes: Record<string, string> = {
    default: "px-4 py-2.5 text-sm",
    sm: "px-3 py-2 text-[12px]",
    lg: "px-6 py-3 text-base",
  };

  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-[0.6rem] font-medium transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-[#2d5a82] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 ${variants[variant]} ${sizes[size]} ${className}`}
      disabled={disabled || loading}
      onClick={onClick}
      {...props}
    >
      {loading && (
        <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      )}
      {!loading && children}
    </button>
  );
}
// -----------------------------------------------------------------------------
// InputField
// -----------------------------------------------------------------------------

export function InputField({
  label,
  helper,
  error,
  className = "",
  children,
  ...props
}: {
  label?: string;
  helper?: string;
  error?: string;
  className?: string;
  children?: ReactNode;
} & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className={`space-y-1 ${className}`}>
      {label && <label className="label">{label}</label>}
      <div className="relative">
        {children && (
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a94a6] pointer-events-none">
            {children}
          </div>
        )}
        <input
          className={`input pl-10 ${error ? "border-[#b3261e] focus:border-[#b3261e] focus:ring-[#b3261e]/20" : ""}`}
          {...props}
        />
      </div>
      {error && <p className="text-[11px] font-medium text-[#b3261e]">{error}</p>}
      {!error && helper && <p className="text-[11px] text-[#6b7280]">{helper}</p>}
    </div>
  );
}

// -----------------------------------------------------------------------------
// Badge
// -----------------------------------------------------------------------------

export function Badge({ children, variant = "neutral", className = "" }: { children?: ReactNode; variant?: "primary" | "success" | "warning" | "danger" | "neutral"; className?: string }) {
  const variants: Record<string, string> = {
    primary: "bg-[#eef3f9] text-[#2d5a82]",
    success: "bg-[#eef7f1] text-[#2e7d4f]",
    warning: "bg-[#fdf3e3] text-[#b26a00]",
    danger: "bg-[#fbeaea] text-[#b3261e]",
    neutral: "bg-[#f1f3f6] text-[#5c6674]",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${variants[variant]} ${className}`}>{children}</span>
  );
}
// -----------------------------------------------------------------------------
// Avatar
// -----------------------------------------------------------------------------

export function Avatar({ src, name, className = "" }: { src?: string; name?: string; className?: string }) {
  const initials = name
    ? name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : "?";
  return (
    <div className={`inline-flex h-8 w-8 items-center justify-center rounded-full bg-[#eef2f7] text-[#4b5563] font-medium text-xs select-none ${className}`}>
      {src ? <img src={src} alt="" className="rounded-full h-full w-full object-cover" /> : initials}
    </div>
  );
}

// -----------------------------------------------------------------------------
// Separator
// -----------------------------------------------------------------------------

export function Separator({ className = "" }: { className?: string }) {
  return <div className={`mx-2 h-[1px] w-[1px] bg-[#d8dce4] flex-shrink-0 ${className}`} />;
}

// -----------------------------------------------------------------------------
// Label
// -----------------------------------------------------------------------------

export function Label({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <label className={`label ${className}`}>{children}</label>;
}

// -----------------------------------------------------------------------------
// Skeleton
// -----------------------------------------------------------------------------

export function Skeleton({ className = "", h = "4", w = "48" }: { className?: string; h?: string; w?: string }) {
  return <div className={`animate-pulse rounded-md bg-[#e4e7ec] h-${h} w-${w} ${className}`} />;
}
// -----------------------------------------------------------------------------
// Dialog / Modal
// -----------------------------------------------------------------------------

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  description?: string;
  children: ReactNode;
}

export function Dialog({ open, onOpenChange, title, description, children }: DialogProps) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center" onClick={() => onOpenChange(false)}>
      <div className="w-full max-w-2xl rounded-[1rem] border border-[#e2e5ec] bg-white shadow-2xl p-6" onClick={(e) => e.stopPropagation()}>
        {title && (
          <div className="mb-2">
            <h2 className="text-lg font-semibold text-[#141923]">{title}</h2>
            {description && <p className="text-sm text-[#6b7280] mt-1">{description}</p>}
          </div>
        )}
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------------
// DropdownMenu
// -----------------------------------------------------------------------------

interface DropdownItem {
  label: string;
  onClick?: () => void;
  icon?: ReactNode;
  disabled?: boolean;
  separator?: boolean;
}

export function DropdownMenu({
  trigger,
  items,
  className = "",
}: {
  trigger: ReactNode;
  items: DropdownItem[];
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="relative inline-block" ref={ref}>
      <Button variant="outline" size="sm" onClick={() => setOpen((o) => !o)} className={className}>
        {trigger}
        <ChevronRight className="w-3 h-3 ml-1" />
      </Button>
      {open && (
        <div className="absolute right-0 mt-2 w-48 rounded-[0.6rem] border border-[#d8dce4] bg-white shadow-lg py-1 z-50">
          {items.map((item, i) => {
            if (item.separator) return <div key={i} className="mx-2 h-[1px] bg-[#eef1f6]" />;
            return (
              <button
                key={i}
                onClick={(e) => { e.stopPropagation(); item.onClick?.(); setOpen(false); }}
                disabled={item.disabled}
                className={`flex w-full items-center gap-2 rounded-[0.4rem] px-3 py-2 text-sm transition ${item.disabled ? "text-[#b7c0d1]" : "text-[#141923] hover:bg-[#f5f7fa]"}`}
              >
                {item.icon && <span className="w-4 h-4">{item.icon}</span>}
                {item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
// -----------------------------------------------------------------------------
// Select
// -----------------------------------------------------------------------------

export function Select({
  label,
  options,
  value,
  onChange,
  className = "",
  helper,
  error,
}: {
  label?: string;
  options: { label: string; value: string }[];
  value: string;
  onChange: (v: string) => void;
  className?: string;
  helper?: string;
  error?: string;
}) {
  return (
    <div className={`space-y-1 ${className}`}>
      {label && <label className="label">{label}</label>}
      <select
        className={`input ${error ? "border-[#b3261e] focus:border-[#b3261e] focus:ring-[#b3261e]/20" : ""}`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {error && <p className="text-[11px] font-medium text-[#b3261e]">{error}</p>}
      {!error && helper && <p className="text-[11px] text-[#6b7280]">{helper}</p>}
    </div>
  );
}

// -----------------------------------------------------------------------------
// Table helpers
// -----------------------------------------------------------------------------

export function TableHeaderCell({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return (
    <th className={`px-4 py-3 text-left text-[11px] font-bold uppercase tracking-wider text-[#6b7280] bg-[#f8fafc] border-b border-[#e9ecef] ${className}`}>
      {children}
    </th>
  );
}

export function TableCell({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <td className={`px-4 py-3 text-sm text-[#141923] border-b border-[#f1f3f6] ${className}`}>{children}</td>;
}