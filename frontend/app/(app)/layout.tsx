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
  { href: "/history", label: "History", icon: "history" },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) return <Spinner />;

  return (
    <div className="min-h-screen bg-[#f5f7fa]">
      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-64 bg-white border-r border-[#e2e5ec] transition-all duration-300 ${
          collapsed ? "-translate-x-full" : "translate-x-0"
        } sm:-translate-x-full sm:translate-x-0`}
      >
        <div className="flex h-16 items-center justify-between px-4 border-b border-[#e2e5ec]">
          <Link href="/dashboard" className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-xl bg-[#2d5a82] text-white">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="h-5 w-5" stroke="currentColor" strokeWidth="1.8">
                <path d="M7 3.75h7l4 4v12.5H7a2 2 0 0 1-2-2v-12.5a2 2 0 0 1 2-2Z" />
                <path d="M14 3.75v4h4M8.5 12h7M8.5 15.5h7" />
              </svg>
            </span>
            <span className={`font-serif text-lg font-bold text-[#141923] ${collapsed ? "hidden" : "block"}`}>DocIntel</span>
          </Link>
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="p-2 text-[#6b7280] hover:text-[#141923] hover:bg-[#f5f7fa] rounded-md"
            aria-label="Toggle navigation"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
        </div>
        <nav className="mt-4 space-y-1 px-3">
          {NAV.map((n) => {
            const active = pathname === n.href || pathname.startsWith(`${n.href}/`);
            return (
              <Link
                key={n.href}
                href={n.href}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${
                  active
                    ? "bg-[#eef3f9] text-[#2d5a82] font-medium"
                    : "text-[#5c6674] hover:bg-[#f5f7fa] hover:text-[#141923]"
                }`}
              >
                <span className={`w-5 text-center ${active ? "text-[#2d5a82]" : "text-[#8a94a6]"}`}>
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
                {collapsed ? "" : n.label}
              </Link>
            );
          })}
        </nav>
        <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-[#e2e5ec] bg-white">
          <div className="flex items-center gap-3">
            <Avatar src={undefined} name={user.email} className="h-8 w-8" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-[#141923] truncate">{user.email}</p>
              <p className="text-xs text-[#6b7280] capitalize truncate">{user.role}</p>
            </div>
          </div>
          <button onClick={logout} className="mt-3 w-full py-2.5 rounded-lg border border-[#d8dce4] text-sm text-[#5c6674] hover:bg-[#f5f7fa] transition-colors">
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className={`ml-0 sm:ml-64 ${collapsed ? "ml-0" : "ml-64"} transition-all duration-300 min-h-screen`}>
        <header className="sticky top-0 z-30 border-b border-[#e2e5ec] bg-white/90 backdrop-blur-sm">
          <div className="flex items-center justify-between px-6 py-4">
            <div className="flex items-center gap-3">
              <h1 className="font-serif text-xl font-bold text-[#141923]">{getPageTitle(pathname)}</h1>
              {pathname !== "/dashboard" && (
                <Link
                  href="/dashboard"
                  className="text-sm text-[#2d5a82] hover:text-[#244a6b] underline underline-offset-4"
                >
                  Back to dashboard
                </Link>
              )}
            </div>
            <div className="hidden sm:flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-[#2e7d4f]" />
              <span className="text-xs text-[#5c6674]">System operational</span>
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
