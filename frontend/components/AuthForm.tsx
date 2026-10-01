"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { supabase } from "@/lib/supabase";
import { Logo } from "@/components/AppShell";
import { Button, ErrorText, Field, Input } from "@/components/ui";

export default function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const { error } =
      mode === "login"
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({ email, password });
    setBusy(false);
    if (error) {
      setError(error.message);
      return;
    }
    router.replace("/studio");
  }

  return (
    <div className="min-h-screen grid place-items-center px-4">
      <div className="w-full max-w-sm gs-fade-up">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <Logo size="lg" />
          <p className="text-sm text-muted">
            {mode === "login"
              ? "Sign in to your creative workspace"
              : "Create your account — start generating in seconds"}
          </p>
        </div>
        <form
          onSubmit={submit}
          className="rounded-xl border border-line bg-surface p-6 space-y-4"
          aria-label={mode === "login" ? "Sign in" : "Sign up"}
        >
          <Field label="Email">
            <Input
              type="email"
              required
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Field label="Password" hint={mode === "signup" ? "At least 6 characters" : undefined}>
            <Input
              type="password"
              required
              minLength={6}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <ErrorText>{error}</ErrorText>
          <Button type="submit" disabled={busy} className="w-full h-11">
            {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-muted">
          {mode === "login" ? (
            <>
              No account?{" "}
              <Link href="/signup" className="gs-focus text-accent hover:underline rounded-sm">
                Sign up
              </Link>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <Link href="/login" className="gs-focus text-accent hover:underline rounded-sm">
                Sign in
              </Link>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
