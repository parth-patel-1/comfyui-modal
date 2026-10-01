"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { api } from "@/lib/api";

export function Logo({ size = "md" }: { size?: "md" | "lg" }) {
  return (
    <span className={`inline-flex items-center gap-2 font-semibold tracking-tight ${size === "lg" ? "text-2xl" : "text-base"}`}>
      <svg width={size === "lg" ? 28 : 20} height={size === "lg" ? 28 : 20} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="2" y="2" width="20" height="20" rx="6" fill="url(#gsg)" />
        <path d="M12 6.5l1.4 3.6 3.6 1.4-3.6 1.4L12 16.5l-1.4-3.6L7 11.5l3.6-1.4L12 6.5z" fill="white" />
        <defs>
          <linearGradient id="gsg" x1="2" y1="2" x2="22" y2="22">
            <stop stopColor="#6d28d9" />
            <stop offset="1" stopColor="#7c5cff" />
          </linearGradient>
        </defs>
      </svg>
      <span>
        Gen<span className="gs-gradient-text">Studio</span>
      </span>
    </span>
  );
}

const LINKS = [
  { href: "/studio", label: "Studio" },
  { href: "/discover", label: "Discover" },
  { href: "/gallery", label: "Gallery" },
  { href: "/credits", label: "Credits" },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isAuthPage = pathname === "/login" || pathname === "/signup";

  const [ready, setReady] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const [balance, setBalance] = useState<number | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    if (isAuthPage) return;
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      if (!data.session) {
        router.replace("/login");
        return;
      }
      setEmail(data.session.user.email ?? null);
      setReady(true);
      api.wallet().then((w) => active && setBalance(w.balance)).catch(() => {});
      api
        .me()
        .then((m) => active && setIsAdmin(m.role === "admin"))
        .catch(() => {});
    });
    const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "SIGNED_OUT") router.replace("/login");
      if (session) setEmail(session.user.email ?? null);
    });
    // refresh balance when returning to credits/studio
    const t = setInterval(() => {
      api.wallet().then((w) => setBalance(w.balance)).catch(() => {});
    }, 15000);
    return () => { active = false; sub.subscription.unsubscribe(); clearInterval(t); };
  }, [isAuthPage, pathname, router]);

  if (isAuthPage) return <>{children}</>;

  if (!ready) {
    return (
      <div className="min-h-screen grid place-items-center bg-bg">
        <div className="gs-shimmer h-1 w-40 rounded-full" aria-label="Loading" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg flex flex-col">
      <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
          <Link href="/studio" className="gs-focus rounded-md" aria-label="GenStudio home">
            <Logo />
          </Link>
          <nav className="flex items-center gap-1" aria-label="Main">
            {LINKS.map((l) => {
              const active = pathname.startsWith(l.href);
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  aria-current={active ? "page" : undefined}
                  className={`gs-focus rounded-lg px-3 py-1.5 text-sm transition-colors ${
                    active ? "bg-accent-soft text-accent font-medium" : "text-muted hover:text-fg hover:bg-surface-2"
                  }`}
                >
                  {l.label}
                </Link>
              );
            })}
            {isAdmin && (
              <Link
                href="/admin"
                aria-current={pathname.startsWith("/admin") ? "page" : undefined}
                className={`gs-focus rounded-lg px-3 py-1.5 text-sm transition-colors ${
                  pathname.startsWith("/admin")
                    ? "bg-accent-soft text-accent font-medium"
                    : "text-muted hover:text-fg hover:bg-surface-2"
                }`}
              >
                Admin
              </Link>
            )}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            {balance !== null && (
              <Link
                href="/credits"
                className="gs-focus inline-flex items-center gap-1.5 rounded-full border border-accent-line bg-accent-soft px-3 py-1 text-xs font-semibold text-accent"
                title="Credit balance — click for details"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M12 2l2.4 5.9L20 10l-5.6 2.1L12 18l-2.4-5.9L4 10l5.6-2.1L12 2z" />
                </svg>
                {balance} credits
              </Link>
            )}
            <span className="hidden sm:block max-w-[180px] truncate text-xs text-faint" title={email ?? undefined}>
              {email}
            </span>
            <button
              onClick={async () => { await supabase.auth.signOut(); router.replace("/login"); }}
              className="gs-focus rounded-lg px-2.5 py-1.5 text-xs text-muted hover:text-fg hover:bg-surface-2"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}
