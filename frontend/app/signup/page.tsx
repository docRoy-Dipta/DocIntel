"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Card, CardContent, CardHeader, ErrorBox, Button, InputField } from "@/components/ui";
import { Mail, Lock } from "lucide-react";
import { useAuth } from "@/lib/auth";

export default function SignupPage() {
  const { signup } = useAuth();
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
      await signup(email, password);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#f5f7fa]">
      <div className="flex min-h-screen items-center justify-center px-4">
        <Card className="w-full max-w-md elevated shadow-lg">
          <CardHeader>
            <div className="flex items-center gap-2 mb-6">
              <span className="grid h-9 w-9 place-items-center rounded-xl bg-[#2d5a82] text-white">
                <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="h-5 w-5" stroke="currentColor" strokeWidth="1.8">
                  <path d="M7 3.75h7l4 4v12.5H7a2 2 0 0 1-2-2v-12.5a2 2 0 0 1 2-2Z" />
                  <path d="M14 3.75v4h4M8.5 12h7M8.5 15.5h7" />
                </svg>
              </span>
              <span className="font-serif text-xl font-bold text-[#141923]">DocIntel</span>
            </div>
            <h2 className="text-lg font-serif font-bold text-[#141923]">Create an account</h2>
            <p className="text-sm text-[#6b7280]">New accounts start as a viewer and can be promoted to admin later.</p>
          </CardHeader>
          <CardContent className="space-y-5">
          <form onSubmit={submit}>
            <ErrorBox message={error} />
            <InputField
              label="Email"
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
              autoComplete="new-password"
              required
              minLength={10}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            >
              <Lock className="w-4 h-4 text-[#6b7280]" />
            </InputField>
            <p className="text-xs text-[#6b7280]">Passwords must be at least 10 characters.</p>
            <Button
              className="w-full"
              type="submit"
              disabled={busy}
            >
              {busy ? (
                <>
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Creating account…
                </>
              ) : "Create account"}
            </Button>
            <p className="text-center text-sm text-[#6b7280]">
              Already have an account?{" "}
              <Link href="/login" className="font-medium text-[#2d5a82] underline underline-offset-2 hover:text-[#244a6b]">
                Sign in
              </Link>
            </p>
          </form>
          </CardContent>
          <div className="border-t border-[#f1f3f6] bg-[#f8fafc]/50 px-4 py-3 rounded-b-[1rem]">
            <div className="flex items-center gap-3 px-3 py-2">
              <svg className="w-4 h-4 text-[#2e7d4f]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" />
              </svg>
              <span className="text-xs text-[#141923]">Your data is encrypted and protected</span>
            </div>
          </div>
        </Card>
      </div>
    </main>
  );
}