"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { ErrorBox } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 lg:grid lg:grid-cols-[1.05fr_.95fr]">
      <section className="relative hidden min-h-screen overflow-hidden bg-indigo-950 px-12 py-12 text-white lg:flex lg:flex-col lg:justify-between xl:px-20">
        <div aria-hidden="true" className="pointer-events-none absolute -right-32 -top-32 h-96 w-96 rounded-full border-[48px] border-orange-400/10 bg-white/[0.03]" />
        <div aria-hidden="true" className="pointer-events-none absolute -bottom-40 -left-24 h-96 w-96 rounded-full border border-white/10" />
        <div className="relative flex items-center gap-3">
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-orange-500 text-white">
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="h-6 w-6" stroke="currentColor" strokeWidth="1.8">
              <path d="M7 3.75h7l4 4v12.5H7a2 2 0 0 1-2-2v-12.5a2 2 0 0 1 2-2Z" />
              <path d="M14 3.75v4h4M8.5 12h7M8.5 15.5h7" />
            </svg>
          </span>
          <span>
            <span className="block text-xl font-bold">DocIntel</span>
            <span className="text-xs text-indigo-200">Document workspace</span>
          </span>
        </div>
        <div className="relative max-w-xl py-12">
          <p className="text-xs font-bold uppercase tracking-[0.22em] text-orange-300">A calmer way to work with paperwork</p>
          <h1 className="mt-5 font-display text-5xl leading-[1.12] xl:text-6xl">Every document, <span className="text-orange-300">in clearer focus.</span></h1>
          <p className="mt-6 max-w-lg text-base leading-7 text-indigo-100">
            Extract, verify, and review invoice details in one thoughtful workspace, with the evidence always close at hand.
          </p>
          <div className="mt-10 grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-4">
              <span className="text-sm font-semibold text-orange-200">Grounded extraction</span>
              <p className="mt-1 text-xs leading-5 text-indigo-100">See where each value came from in the source.</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-4">
              <span className="text-sm font-semibold text-orange-200">Review with confidence</span>
              <p className="mt-1 text-xs leading-5 text-indigo-100">Keep validation and corrections in one place.</p>
            </div>
          </div>
        </div>
        <p className="relative text-xs text-indigo-300">A clear view of every file, page, and decision.</p>
      </section>

      <section className="relative flex min-h-screen items-center justify-center overflow-hidden px-5 py-12 sm:px-8">
        <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-orange-100/70 blur-3xl" />
        <div className="relative w-full max-w-md">
          <div className="mb-7 flex items-center gap-3 lg:hidden">
            <span className="grid h-11 w-11 place-items-center rounded-2xl bg-orange-500 text-white">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="h-5 w-5" stroke="currentColor" strokeWidth="1.8">
                <path d="M7 3.75h7l4 4v12.5H7a2 2 0 0 1-2-2v-12.5a2 2 0 0 1 2-2Z" />
                <path d="M14 3.75v4h4M8.5 12h7M8.5 15.5h7" />
              </svg>
            </span>
            <span className="text-lg font-bold text-indigo-950">DocIntel</span>
          </div>
          <form onSubmit={submit} className="card space-y-5 rounded-[1.75rem] p-7 shadow-lg shadow-indigo-950/5 sm:p-9">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-orange-600">Welcome back</p>
              <h2 className="mt-2 font-display text-3xl text-indigo-950">Sign in to your workspace</h2>
              <p className="mt-2 text-sm text-slate-500">Your documents and review queue are ready when you are.</p>
            </div>
            <ErrorBox message={error} />
            <label className="block text-sm font-semibold text-slate-700">
              Email
              <input className="input mt-2" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label className="block text-sm font-semibold text-slate-700">
              Password
              <input className="input mt-2" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
            <button className="btn-primary w-full py-3" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
            <p className="text-center text-sm text-slate-500">
              Don't have an account?{" "}
              <a href="/signup" className="font-semibold text-indigo-600 hover:text-indigo-800 underline">
                Sign up
              </a>
            </p>
            <p className="text-center text-xs text-slate-400">Secure access to your document workspace</p>
          </form>
        </div>
      </section>
    </main>
  );
}
