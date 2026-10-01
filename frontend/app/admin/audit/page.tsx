"use client";

import { useEffect, useState } from "react";
import { adminApi } from "@/lib/api";
import type { AuditEntry } from "@/lib/types";
import { Badge, Button, Card, ErrorText, Spinner } from "@/components/ui";

function tone(action: string): "success" | "danger" | "warning" | "info" | "neutral" {
  if (action.startsWith("deploy")) return "info";
  if (action.includes("suspend") || action === "pricing.update") return "warning";
  if (action.includes("adjust") || action.includes("grant")) return "success";
  if (action.startsWith("user.")) return "danger";
  return "neutral";
}

export default function AdminAuditPage() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    adminApi.audit().then(setEntries).catch((e) => setError(e.message));
  }, []);

  return (
    <div className="space-y-4">
      <ErrorText>{error}</ErrorText>
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <span className="text-sm font-medium">Admin actions (newest first)</span>
          <Button variant="ghost" className="h-8 px-2 text-xs" onClick={() => adminApi.audit().then(setEntries)}>
            Refresh
          </Button>
        </div>
        {entries === null ? (
          <div className="grid place-items-center py-12"><Spinner className="text-accent" /></div>
        ) : entries.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-muted">No admin activity yet.</p>
        ) : (
          <ul className="divide-y divide-[var(--line)]">
            {entries.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
                <Badge tone={tone(a.action)}>{a.action}</Badge>
                {a.target && (
                  <span className="font-mono text-xs text-muted">
                    {a.target.length > 40 ? `${a.target.slice(0, 40)}…` : a.target}
                  </span>
                )}
                {a.payload && Object.keys(a.payload).length > 0 && (
                  <span className="max-w-md truncate font-mono text-xs text-faint">
                    {JSON.stringify(a.payload)}
                  </span>
                )}
                <span className="ml-auto whitespace-nowrap text-[11px] text-faint">
                  {a.admin_email ?? "unknown"} · {new Date(a.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}