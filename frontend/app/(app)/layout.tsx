"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Spinner, Avatar } from "@/components/ui";
import { useAuth } from "@/lib/auth";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "dashboard" },
  { href: "/upload", label: "Upload", icon: "upload" },
  { href: "/documents", label: "Documents", icon: "documents" },
  { href: "/compare", label: "Compare", icon: "compare" },
  { href: "/search", label: "Search", icon: "search" },
  { href: "/history", label: "History", icon: "history", adminOnly: true },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [navExpanded, setNavExpanded] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) return <Spinner />;

  const navItems = user.role === "admin" ? NAV : NAV.filter((n) => !n.adminOnly);

  return (
    <div className="min-h-screen overflow-x-hidden bg-[#f5f7fa]">
      {mobileOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-30 cursor-default bg-[#141923]/35 backdrop-blur-[2px] lg:hidden"
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex h-screen w-64 flex-col overflow-hidden border-r border-[#e2e5ec] bg-white shadow-sm transition-transform duration-300 ease-out ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        } lg:translate-x-0`}
      >
        <div className="flex h-16 shrink-0 items-center justify-between border-b border-[#e2e5ec] px-2 lg:px-4">
          <Link href="/dashboard" className="flex min-w-0 items-center gap-2" aria-label="DocIntel dashboard">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-[#2d5a82] text-white">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="h-5 w-5" stroke="currentColor" strokeWidth="1.8">
                <path d="M7 3.75h7l4 4v12.5H7a2 2 0 0 1-2-2v-12.5a2 2 0 0 1 2-2Z" />
                <path d="M14 3.75v4h4M8.5 12h7M8.5 15.5h7" />
              </svg>
            </span>
            <span className="truncate font-serif text-lg font-bold text-[#141923]">DocIntel</span>
          </Link>
          <div className="ml-auto flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={() => setNavExpanded((current) => !current)}
              className="hidden h-8 w-8 items-center justify-center rounded-lg text-[#6b7280] transition-colors hover:bg-[#f5f7fa] hover:text-[#141923] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2d5a82] lg:inline-flex"
              aria-label={navExpanded ? "Hide navigation items" : "Show navigation items"}
              aria-expanded={navExpanded}
              aria-controls="primary-navigation"
              title={navExpanded ? "Hide navigation items" : "Show navigation items"}
            >
              <svg aria-hidden="true" className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="1.8"
                  d={navExpanded ? "m6 9 6 6 6-6" : "m6 15 6-6 6 6"}
                />
              </svg>
            </button>
            <button
              type="button"
              onClick={() => setMobileOpen(false)}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[#6b7280] transition-colors hover:bg-[#f5f7fa] hover:text-[#141923] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2d5a82] lg:hidden"
              aria-label="Close navigation"
            >
              <svg aria-hidden="true" className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
        </div>
        <nav
          id="primary-navigation"
          aria-label="Primary navigation"
          className={`min-h-0 flex-1 flex-col space-y-1 overflow-y-auto px-3 py-4 ${
            navExpanded ? "flex" : "flex lg:hidden"
          }`}
        >
          {navItems.map((n) => {
            const active = pathname === n.href || pathname.startsWith(`${n.href}/`);
            return (
              <Link
                key={n.href}
                href={n.href}
                onClick={() => setMobileOpen(false)}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${
                  active
                    ? "bg-[#eef3f9] text-[#2d5a82] font-medium"
                    : "text-[#5c6674] hover:bg-[#f5f7fa] hover:text-[#141923]"
                }`}
              >
                <span className={`w-5 shrink-0 text-center ${active ? "text-[#2d5a82]" : "text-[#8a94a6]"}`}>
                  {n.icon === "dashboard" && (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
                    </svg>
                  )}
                  {n.icon === "upload" && (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                  )}
                  {n.icon === "documents" && (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                  )}
                  {n.icon === "compare" && (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                    </svg>
                  )}
                  {n.icon === "search" && (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                    </svg>
                  )}
                  {n.icon === "history" && (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  )}
                </span>
                <span>{n.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto shrink-0 border-t border-[#e2e5ec] bg-white p-3 lg:p-4">
          <div className="flex items-center gap-3">
            <Avatar src={undefined} name={user.email} className="h-9 w-9 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-[#141923] truncate">{user.email}</p>
              <p className="text-xs text-[#6b7280] capitalize truncate">{user.role}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={logout}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-[#d8dce4] py-2.5 text-sm text-[#5c6674] transition-colors hover:bg-[#f5f7fa] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2d5a82]"
            aria-label="Sign out"
          >
            <svg aria-hidden="true" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M10 17l5-5-5-5m5 5H3m9-9h6a2 2 0 012 2v14a2 2 0 01-2 2h-6" />
            </svg>
            <span>Sign out</span>
          </button>
        </div>
      </aside>

      <div className="min-h-screen min-w-0 lg:ml-64">
        <header className="sticky top-0 z-20 border-b border-[#e2e5ec] bg-white/90 backdrop-blur-sm">
          <div className="flex min-h-16 items-center justify-between gap-4 px-4 py-3 sm:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <button
                type="button"
                onClick={() => setMobileOpen(true)}
                className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[#5c6674] transition-colors hover:bg-[#f5f7fa] hover:text-[#141923] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2d5a82] lg:hidden"
                aria-label="Open navigation"
                aria-expanded={mobileOpen}
                aria-controls="primary-navigation"
              >
                <svg aria-hidden="true" className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              </button>
              <div className="min-w-0">
                <h1 className="truncate font-serif text-xl font-bold text-[#141923]">{getPageTitle(pathname)}</h1>
                {pathname !== "/dashboard" && (
                  <Link
                    href="/dashboard"
                    className="hidden text-sm text-[#2d5a82] underline underline-offset-4 hover:text-[#244a6b] lg:inline"
                  >
                    Back to dashboard
                  </Link>
                )}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <div className="hidden items-center gap-2 sm:flex">
                <span className="h-1.5 w-1.5 rounded-full bg-[#2e7d4f]" />
                <span className="text-xs text-[#5c6674]">System operational</span>
              </div>
            </div>
          </div>
        </header>
        <main className="px-6 py-8">{children}</main>
      </div>
    </div>
  );
}

function getPageTitle(pathname: string): string {
  const titles: Record<string, string> = {
    "/dashboard": "Dashboard",
    "/upload": "Upload Documents",
    "/documents": "Documents",
    "/compare": "Cross-Document Verification",
    "/search": "Search",
    "/history": "Processing History",
  };
  return titles[pathname] || "DocIntel";
}
