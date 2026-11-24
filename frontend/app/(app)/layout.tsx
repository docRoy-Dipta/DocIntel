"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/upload", label: "Upload" },
  { href: "/documents", label: "Documents" },
  { href: "/compare", label: "Compare" },
  { href: "/search", label: "Search" },
  { href: "/history", label: "History" },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) return <Spinner />;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 shadow-sm backdrop-blur">
        <div className="bg-indigo-950 text-indigo-50">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-2 text-xs">
            <span>Document intelligence, with clarity and confidence</span>
            <span className="hidden items-center gap-2 sm:flex"><span className="h-1.5 w-1.5 rounded-full bg-orange-400" /> Your secure workspace</span>
          </div>
        </div>
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-4 py-3 md:gap-6">
          <Link href="/dashboard" className="flex shrink-0 items-center gap-2.5" aria-label="DocIntel dashboard">
            <span className="grid h-10 w-10 place-items-center rounded-2xl bg-orange-500 text-white shadow-sm">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="h-5 w-5" stroke="currentColor" strokeWidth="1.8">
                <path d="M7 3.75h7l4 4v12.5H7a2 2 0 0 1-2-2v-12.5a2 2 0 0 1 2-2Z" />
                <path d="M14 3.75v4h4M8.5 12h7M8.5 15.5h7" />
              </svg>
            </span>
            <span className="leading-tight">
              <span className="block text-lg font-bold text-indigo-950">DocIntel</span>
              <span className="block text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Document workspace</span>
            </span>
          </Link>
          <nav aria-label="Main navigation" className="flex flex-1 flex-wrap items-center gap-1">
            {NAV.map((n) => {
              const active = pathname === n.href || pathname.startsWith(`${n.href}/`);
              return (
                <Link key={n.href} href={n.href} className={`rounded-full px-3 py-2 text-sm transition ${active ? "bg-indigo-50 font-semibold text-indigo-900" : "text-slate-600 hover:bg-slate-100 hover:text-indigo-900"}`}>
                  {n.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm text-slate-600">
            <span className="hidden text-right sm:block">{user.email} <span className="ml-1 rounded-full bg-orange-50 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-orange-700">{user.role}</span></span>
            <button className="btn-secondary" onClick={logout}>Sign out</button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6 md:px-6 md:py-8">{children}</main>
    </div>
  );
}
