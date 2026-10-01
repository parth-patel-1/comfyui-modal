"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Spinner } from "@/components/ui";

const TABS = [
  { href: "/admin", label: "Overview", exact: true },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/spending", label: "Spending" },
  { href: "/admin/settings", label: "Settings & Pricing" },
  { href: "/admin/engines", label: "Engines & GPU" },
  { href: "/admin/audit", label: "Audit log" },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [role, setRole] = useState<"user" | "admin" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .me()
      .then((m) => setRole(m.role))
      .catch((e) => setError(e instanceof Error ? e.message : "not authorized"));
  }, []);

  if (error || (role && role !== "admin")) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-24 text-center space-y-3">
        <h1 className="text-lg font-semibold">Admin access required</h1>
        <p className="text-sm text-muted">
          {error ?? "Your account does not have admin permissions."}
        </p>
      </div>
    );
  }
  if (!role) {
    return (
      <div className="grid place-items-center py-32">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">
          Gen<span className="gs-gradient-text">Studio</span> Admin
        </h1>
        <nav className="mt-3 flex flex-wrap items-center gap-1" aria-label="Admin">
          {TABS.map((t) => {
            const active = t.exact ? pathname === t.href : pathname.startsWith(t.href);
            return (
              <Link
                key={t.href}
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={`gs-focus rounded-lg px-3 py-1.5 text-sm transition-colors ${
                  active
                    ? "bg-accent-soft text-accent font-medium"
                    : "text-muted hover:text-fg hover:bg-surface-2"
                }`}
              >
                {t.label}
              </Link>
            );
          })}
        </nav>
      </div>
      {children}
    </div>
  );
}