"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import type { Transaction } from "@/lib/types";
import { Card, ErrorText, Spinner } from "@/components/ui";

export default function CreditsPage() {
  const [balance, setBalance] = useState<number | null>(null);
  const [txs, setTxs] = useState<Transaction[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.wallet().then((w) => setBalance(w.balance)).catch((e) => setError(e.message));
    supabase.auth
      .getSession()
      .then(({ data }) => {
        const uid = data.session?.user.id;
        if (!uid) return;
        return supabase
          .from("credit_transactions")
          .select("id, delta, balance_after, kind, note, created_at")
          .eq("user_id", uid)
          .order("created_at", { ascending: false })
          .limit(50)
          .then(({ data: rows, error: e }) => {
            if (e) setError(e.message);
            else setTxs((rows ?? []) as unknown as Transaction[]);
          });
      })
      .catch(() => setTxs([]));
  }, []);

  return (
    <div className="mx-auto max-w-3xl space-y-5 px-4 py-8">
      <h1 className="text-lg font-semibold tracking-tight">Credits</h1>

      <Card className="p-6">
        <p className="text-xs uppercase tracking-wide text-muted">Available balance</p>
        {balance === null ? (
          <Spinner className="mt-2 text-accent" />
        ) : (
          <p className="mt-1 text-4xl font-semibold tracking-tight">
            {balance} <span className="gs-gradient-text">credits</span>
          </p>
        )}
        <p className="mt-2 text-xs text-faint">
          Credits are charged when a job starts and refunded automatically if it fails or is canceled.
        </p>
      </Card>

      {error ? <ErrorText>{error}</ErrorText> : null}

      <Card className="overflow-hidden">
        <div className="border-b border-line px-4 py-3 text-sm font-medium">Recent activity</div>
        {txs === null ? (
          <div className="grid place-items-center py-10"><Spinner className="text-accent" /></div>
        ) : txs.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-muted">No transactions yet.</p>
        ) : (
          <ul className="divide-y divide-[var(--line)]">
            {txs.map((t) => (
              <li key={t.id} className="flex items-center gap-3 px-4 py-3">
                <span
                  className={`font-mono text-sm font-semibold ${
                    t.delta >= 0 ? "text-success" : "text-fg"
                  }`}
                >
                  {t.delta >= 0 ? "+" : ""}
                  {t.delta}
                  <span className="ml-1.5 text-[10px] font-normal text-faint">
                    → {t.balance_after}
                  </span>
                </span>
                <span className="text-sm text-muted">{t.note || t.kind.replaceAll("_", " ")}</span>
                <span className="ml-auto whitespace-nowrap text-[11px] text-faint">
                  {new Date(t.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
