"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Card, CardHeader, CardContent, ErrorBox, Button, InputField } from "@/components/ui";
import { Mail, Lock } from "lucide-react";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login } = useAuth();
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#f5f7fa]">
      <div className="flex min-h-screen items-center justify-center px-4">
        <Card className="w-full max-w-[440px] elevated shadow-xl">
          <CardHeader>
            <div className="flex items-center gap-2 mb-2">
              <span className="grid h-10 w-10 place-items-center rounded-2xl bg-[#2d5a82] text-white">
                <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="h-5 w-5" stroke="currentColor" strokeWidth="1.8">
                  <path d="M7 3.75h7l4 4v12.5H7a2 2 0 0 1-2-2v-12.5a2 2 0 0 1 2-2Z" />
                  <path d="M14 3.75v4h4M8.5 12h7M8.5 15.5h7" />
                </svg>
              </span>
              <span className="font-serif text-2xl font-bold text-[#141923] tracking-tight">DocIntel</span>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-2">
              <h2 className="text-2xl font-serif font-bold text-[#141923] tracking-tight">Welcome back</h2>
              <p className="text-sm text-[#6b7280]">Sign in to your document workspace</p>
            </div>
            <form onSubmit={submit} className="space-y-4">
              <ErrorBox message={error} />
              <InputField
                label="Email address"
                placeholder="you@company.com"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              >
                <Mail className="w-4 h-4 text-[#6b7280]" />
              </InputField>
              <InputField
                label="Password"
                placeholder="••••••••"
                type="password"
                autoComplete="current-password"
                required
                minLength={10}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              >
                <Lock className="w-4 h-4 text-[#6b7280]" />
              </InputField>
              <Button
                className="w-full py-3"
                type="submit"
                disabled={busy}
              >
                {busy ? (
                  <>
                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    Signing in…
                  </>
                ) : (
                  "Sign in"
                )}
              </Button>
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t border-[#e2e5ec]"></span>
              </div>
              <div className="relative flex justify-center text-xs">
                <span className="bg-[#f5f7fa] px-2 text-[#6b7280]">Continue with</span>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Button variant="outline" className="w-full py-2.5" onClick={() => {}}>
                <svg className="w-4 h-4 text-[#6b7280]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
                Google
              </Button>
              <Button variant="outline" className="w-full py-2.5" onClick={() => {}}>
                <svg className="w-4 h-4 text-[#6b7280]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-5 0a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
                Microsoft
              </Button>
            </div>
            <p className="text-center text-sm text-[#6b7280] space-y-1">
              Don't have an account?{" "}
              <Link href="/signup" className="font-medium text-[#2d5a82] underline underline-offset-2 hover:text-[#244a6b]">
                Create an account
              </Link>
            </p>
          </form>
          </CardContent>
          <div className="border-t border-[#f1f3f6] bg-[#f8fafc]/50 px-6 py-4 rounded-b-[1rem]">
            <p className="text-xs text-[#6b7280] text-center">
              Secure access to your document workspace
            </p>
          </div>
        </Card>
      </div>
    </main>
  );
}
